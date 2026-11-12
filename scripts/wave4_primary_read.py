#!/usr/bin/env python3
"""Wave 4's primary read: the order check of R5 item 2, then, only if it passes, A5 to A9.

    python scripts/wave4_primary_read.py --poster-dir DIR --login FILE \\
        --api URL --campaign cmp_88cf9e875edba15371e6d3f7 \\
        --deviation-out FILE --output FILE

The registration is ``docs/reviews/2026-11-10-wave-4-registration.md`` (part 6; Amendment 2;
Amendment 3 A2-A10 with readings R1-R12; Amendment 4 points 1-5) and the methodologist's
ruling ``docs/reviews/2026-11-10-wave-4-registration/r5-arm-source-ruling-v2.txt`` (T1-T7,
section 4, section 6.3 item 4, section 9, section 11). Where the registered text and a
convenience differ, the registered text is followed and the harder reading taken.

One run of this script is one read. It makes no retry, picks no source over another, mends
nothing and has no option to skip or relax a part. Exit codes: 0 the read was made; 1 not
ready (a recorded constant is missing, the arguments or the login file are not as expected),
no request made; 2 the order check failed (test (i)); 3 the provider test of Amendment 4 point
4 failed (counts only; run ids and their two times to ``--deviation-out``); 4 the read was
not made (a request after the order check passed failed, or a row named another run, an
unlisted commit or one commit twice, or had a non-boolean clean: an added integrity stop;
counts only). A missing row is not a stop: it is counted as a miss (A3). If the
``--deviation-out`` file cannot be created or written at a stop, one fixed line says so (no
path, no traceback) and the stop keeps its exit code.

``--output`` names a new file (created 0600, refused if it exists, before any request); every
line printed to stdout is also written to it, byte for byte, flushed line by line, so the
output that is filed is the output that was printed.

Departures from the spec (``r5-read-spec.md``), each decided before commit:

- The provider-test deviation file carries each run's two served times beside its id
  (Amendment 4 point 4 applies test (i), which puts the ids and the two times in the log).
- No "clean without usable test" consistency figure is printed (spec open point 25): R12
  reads no clean field for the usable-test count, and the read prints no other figure.
- The script keeps its name (``wave4_primary_read.py``) and the ``--poster-dir`` argument,
  and uses the standard library only (no httpx).
- A missing row is a miss, not a stop (the methodologist's reading of 2026-11-12, items 1
  and 4): it is counted as a miss, and each missing row is listed after the decision word.

What it keeps. Every parsed document goes straight to an extractor that returns only the
fields listed in ``KEPT``; the rest is never stored, logged or printed. No table of arms by
run is ever printed. Every figure is computed in integers and ``fractions.Fraction``.

Several constants must be recorded by the delivery manager before the script is committed
(``RECORDED``): the four poster files' names and full sha256, the 48 standing run ids and the
place rule of T7. The poster files' JSON shapes are fixed in the parsers, from the poster's
source text (``wave4_post.py``, sha256 ``b30ca68e...50b105``; lines cited at each parser).
Until every constant is recorded, the script prints ``not ready: <name> not recorded``, makes
no request and exits 1.

Navigation
----------
What it is:   The one script that reads Wave 4's primary result: the order check of R5 item 2
              with the ruling's T1-T7, then the sign-flip test, the interval, the two
              sensitivity results and the decision word of A5-A9.
What it does: Hashes and parses the poster's plan, plan copy and out files; reads the campaign
              record's ``run_id``/``s1`` and each listed run record; runs tests (a)-(i) with
              T1-T7 and section 4; on a pass reads the standing ``S1`` runs' events (provider
              test, R12) and the 48 runs' ledger rows, and prints the read.
How:          Standard library only. All I/O goes through injected callables: ``read_file``
              (bytes of a path), ``open_getter`` (returns a GET callable bound to the API),
              ``write_deviation``, ``open_output`` and ``path_exists``. The default getter
              is urllib with no redirect and no retry; tests inject fakes.
Layer:        tooling — docs/ARCHITECTURE.md#44-outer-layers
ADRs:         none
Works with:   docs/reviews/2026-11-10-wave-4-registration.md (the registered rules),
              docs/reviews/2026-11-10-wave-4-registration/r5-arm-source-ruling-v2.txt (the
              ruling), docs/reviews/2026-11-10-wave-4-registration/wave-record-notes.md (the
              names of test (h)), src/crb/server/schemas.py (``RunOut``, ``GradeRowOut``,
              ``StepEventOut``, ``Page``), src/crb/server/campaigns.py (``campaign_view``)
Tested by:    tests/test_wave4_primary_read.py
Touch when:   never for a new repository; Wave 4's registration or ruling changes a rule of
              the read (a new commit and sha256, recorded before any row is read).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import product
from pathlib import Path
from typing import Any, TypeGuard

# ---------------------------------------------------------------------------
# registered constants (each with its source)
# ---------------------------------------------------------------------------

SCRIPT_NAME = "wave4_primary_read"
#: REG 636; RUL section 8.
CAMPAIGN_ID = "cmp_88cf9e875edba15371e6d3f7"
REPOS: tuple[str, ...] = ("click", "cobra")

#: The first 15 commits of each Amendment 1 list, in list order (REG 496-510, 532-546,
#: 576-590, 598-612; cut by Amendment 2, REG 709-718).
LISTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("click", "XS"): (
        "b5464b7e065bdfd952b1532880941f1be07e4e2b",
        "0de3704747c1399d019f1d94caeefe20123b6ef0",
        "c326df95e9e3da0425360e030413f6a3ee25fdee",
        "3f91d2154ebc47651f0cd9798250a03821473521",
        "589ca314ae8d200ff55263a2c49c8ae6341866f3",
        "1b0e19f50595a07957bd96a600c37cd44b7e0cc3",
        "71f2bafa541e7f798834e74076786ff4281ac83e",
        "762c97eef7c1b3779678992f26a553a2a8c80793",
        "1a4d8c1bb1e8f8e214ede7223bd2c05dc2ce006a",
        "f316d5cb3aa89b57c14aee54da6ac9062ac5bec4",
        "32ae2acd3474a57d2450ea849545b2e1258bf76a",
        "d340b0c1202284a1b9d0ca892549208527d586ce",
        "4fd2fea0db423d242aedcae0a5f664efe0a93484",
        "ac6a2acfdb4550c35ce69ce54db502ba96c96324",
        "a3321c9ca14ddb951f04ac981f275b0de2f46208",
    ),
    ("click", "S"): (
        "91de59c6c8abc8251e7af551cd4546cc964288af",
        "7d05a59b9d46a415d85937630d1d812cf477f60a",
        "c653ec820093ed1dda41aae8d35bff7834b0344a",
        "becbde5cf416441627f779e8dd34e57738ee1c1f",
        "149683755e07b62de7480b3a60a714f0a8b6618f",
        "ecb99836a44367bad62960045d586e31e4a95766",
        "546f2851f414b07413777ebcae89b2c21a685252",
        "1b524bb30d0bd39528369c7029b9296e7663cf19",
        "380008389b32ca2b7de7c73f670a9eee1562004e",
        "f25f697a439acc2b0d84aa8f5413330f4e2e75cf",
        "2468b70997a6ec27ced4b4867954c90da3f92075",
        "b36e3ede781b388ae8135af61e83269e211acdf1",
        "6de212151893e4072ca21779b7b6f4cb82452f51",
        "1c20dc6e724cd5625faaa17b715ba928d44c08bf",
        "5fc3423ae54990cec5a8b41d2c7b489da41475b0",
    ),
    ("cobra", "XS"): (
        "a73b9c391a9489d20f5ee1480e75d3b99fc8c7e2",
        "7ce08e227e8c9db9b243dfef1e792af31d19cdd0",
        "8822449c0fb9575f1d2453e80cd3e55ab8fc2844",
        "5155946348eed0f79a76f7743407c0c933e3b5f0",
        "8a63648dd905e5c96bee06e6851a894fc75aa058",
        "22b617914c8890ba20db7ceafcdc2ef4ca4817d3",
        "e392f3204db0445f1f4ad47448b04d8c8ad04c2a",
        "ed7b60e2987d2cd54d6a391379e33effdacdadf9",
        "7790bf97fd40e285913066cf65387ad281cd6c2e",
        "6f84ef48750fe6355a267117837ba6ee3da254e7",
        "b9ca5949e2f58373e8e4c3823c213401f7d9d0e3",
        "fdee73b4a0d0be3e233b968ab038866b7cd99772",
        "b4f979ae352828a0153281b590771ce9588d67f8",
        "95f2f73ed97e57387762620175ccdc277a8597a0",
        "a97f9fd47b290016526c8af2dac0531fea5cd773",
    ),
    ("cobra", "S"): (
        "b711e8760b73c6aa1b4aa1bef3a26da5926f175d",
        "2d94892a8bec681d65a129e0a94b2e0d87e52cb9",
        "02a0d2fbc9e61d26f8e5979749f6030964a55a3e",
        "df12a0a24975e4c9f278e62927ca08d000b9be71",
        "23a6174c7f9d0c64a48e634054bdf6886fb7fbba",
        "04318720db1743b8488c86b2f7dca6d9663cb2f2",
        "a15d0990180cf0d99905ad41201211f8ac3cab53",
        "890302a35f578311404a462b3cdd404f34db3720",
        "675ae5f5a98cc705a6d54f4c487ab81230604137",
        "9054739e08187aab9294b7a773d54c92fabc23d3",
        "212ea4078323771dc49b6f25a41d84efbaac3a4c",
        "e0fefb2b76210bd9833a12d47b2a3cf83b9f47ab",
        "c3573e220c93941b06812483ee96ceaf5fa5e5cc",
        "5bef9d8d87ad1a1c73e74361bad9e38b3469a58e",
        "45e521ea93e2270ef7333487f0a87e3887de2da9",
    ),
}

A0S1S1A0 = ("A0", "S1", "S1", "A0")
S1A0A0S1 = ("S1", "A0", "A0", "S1")
#: Amendment 2, "The batches and their orders" (REG 744-757): (cell, list positions, order).
#: Batches 1/3/5 are XS positions 1-5/6-10/11-15; batches 2/4/6 are S (REG 191-197).
ORDERS: dict[tuple[str, int], tuple[str, ...]] = {
    ("click", 1): A0S1S1A0,
    ("click", 2): A0S1S1A0,
    ("click", 3): A0S1S1A0,
    ("click", 4): A0S1S1A0,
    ("click", 5): A0S1S1A0,
    ("click", 6): S1A0A0S1,
    ("cobra", 1): S1A0A0S1,
    ("cobra", 2): A0S1S1A0,
    ("cobra", 3): A0S1S1A0,
    ("cobra", 4): S1A0A0S1,
    ("cobra", 5): A0S1S1A0,
    ("cobra", 6): A0S1S1A0,
}
BATCH_KEYS: tuple[tuple[str, int], ...] = tuple((r, b) for r in REPOS for b in range(1, 7))


def batch_cell(b: int) -> str:
    """XS for batches 1, 3, 5; S for 2, 4, 6 (REG 191-197)."""
    return "XS" if b % 2 == 1 else "S"


def batch_commits(repo: str, b: int) -> tuple[str, ...]:
    """The five listed commits of batch ``b`` of ``repo``, in list order."""
    start = 5 * ((b - 1) // 2)
    return LISTS[(repo, batch_cell(b))][start : start + 5]


LISTED: frozenset[str] = frozenset(c for lst in LISTS.values() for c in lst)

#: A2 item 3 and REG 862-864: the first filing of click batch 3, and the four that stand.
SHORT_FIRST_FILING = "98fe708c"
SHORT_CLICK3 = ("8a258976", "78b4d435", "3f67a4d0", "5fd4dc40")
ATTEMPT1_KEY = "click-3/1#attempt1"
ATTEMPT1_PLAN_KEY = "click-3/1"

#: Amendment 4 point 3 (REG 1768-1776): the S1 ``test_author`` value, compared exactly.
L_VALUE = "editblock:gpt-oss-120b"
L_SOURCE = "DL-378, docs/DECISION-LOG.md line 175, and docs/OPERATOR.md line 1432, at 7bb03d6c"
#: Test (h): the run record's field names (wave-record-notes 83-86; RUL section 10).
H_FIELDS: tuple[tuple[str, str], ...] = (
    ("filing time", "created"),
    ("end time", "finished"),
    ("status", "status"),
    ("row count", "counts.rows"),
    ("commits", "task_ids"),
    ("kind", "kind"),
)

#: The 97.5% point of Student's t for df 1..11, each rounded up to 4 decimals (A7 prints
#: 2.2010 for df 11; the same rule for every df is the harder reading, spec open point 5).
T975: dict[int, str] = {
    1: "12.7063",
    2: "4.3027",
    3: "3.1825",
    4: "2.7765",
    5: "2.5706",
    6: "2.4470",
    7: "2.3647",
    8: "2.3061",
    9: "2.2622",
    10: "2.2282",
    11: "2.2010",
}
FIFTEEN_POINTS = Fraction(15, 100)
NINE_IN_TEN = 108  # of 120 expected S1 attempts (A9 item 3)
SIX_BATCHES = 6  # R4
AUTHOR_HIT_AT = 6  # "more than half" of 10 (A8 item 2)
AUTHORING_PREFIX = "authoring:"  # R12 item 3 (d), REG's literal
PAGE_LIMIT = 500  # schemas.py PAGE_MAX

#: The five "Taken on trust" lines, word for word (REG 1655-1669 = RUL 172-182), without tags.
TRUST_LINES: tuple[str, ...] = (
    "That the poster sent the plan's `body` for place `p` as its `p`th POST of the batch, "
    "and sent it unchanged. This rests on the poster's source text (`wave4_post.py` line "
    "150, sha256 `b30ca68e...50b105`) and on the delivery manager's statement that the plan "
    "file was not rewritten by the poster.",
    "That the four files are as they were at filing time. The hashes were first recorded on "
    "2026-11-12, after the wave. The script cannot use file times.",
    "Whether any tie was made by inference. No kept file says.",
    "That `refile.py` filed batch 3 again from the same plan entries.",
    "That the poster source text of item 1, at that sha256, is the text that ran for every "
    "batch. The deviation log (annex, D4) records a poster crash before batch 3. No kept "
    "file shows which text ran after it. T7 rests on the same text.",
)
S1_FLAG_SENTENCE = (
    "For all 49 runs the product's `s1` flag agreed with the `arm` field of the body."
)
FAIL_FOOTER = (
    "No figure is printed. The read waits. Test (i): no run is dropped, no batch is filed "
    "again, no row is set aside; only Paul, in writing, can say whether the primary is then "
    "read."
)
STOP_B_SENTENCE = (
    "A reader who holds the widest reading should treat every Wave 4 result as coming from "
    "a wave that passed its stop (b) on the operator's decision, made after 110 pooled rows "
    "were seen."
)
FIXED_SENTENCES: tuple[str, ...] = (
    "A rejection says that the arms differ; the direction and size are read from the "
    "estimate of item 2.",
    "No error rate is quoted for the call.",
    "Under option B the claim is about the average over the listed commits of both "
    "repositories together; nothing is claimed for either repository alone.",
    "This interval is approximate: no interval of this form has guaranteed coverage for every "
    "distribution of batch sums, and it is reported as a description, not as a second test.",
)
PROVIDER_STOP_LINES = (
    "test author provider not shown as cerebras",
    "runs with no author.attempt event: {n1}",
    "runs with another provider value: {n2}",
)

#: RUL T1: the truncated sha256 of each poster file (prefix, suffix). The full value must be
#: recorded in ``RECORDED.file_sha256`` and must agree with these.
FILE_SHA256_TRUNCATED: dict[str, tuple[str, str]] = {
    "plan": ("ae705b68", "fb45a"),
    "pre_s3": ("a3c592cd", "2970fd"),
    "click_out": ("27b2747e", "4c4170"),
    "cobra_out": ("59d7eefc", "06e0e1"),
}
FILE_ROLES: tuple[str, ...] = ("plan", "pre_s3", "click_out", "cobra_out")

#: The fields kept from each source (RUL sections 5 and 11; spec section 1.4). Everything
#: else is dropped by the extractor that receives the parsed document.
KEPT: dict[str, tuple[str, ...]] = {
    "plan": ("body", "slot"),
    "out": ("run.id",),
    "campaign": ("runs[].run_id", "runs[].s1"),
    "run (any listed)": ("id", "kind", "task_ids", "created", "finished"),
    "run (the 49)": (
        "status", "counts.rows", "repo", "builder", "model",
        "provider", "budget", "max_cost_usd", "builder_config", "retain",
    ),
    "event": ("seq", "action", "payload.provider (author.attempt)", "payload.task"),
    "row": ("run_id", "task_id", "clean", "error (S1 runs only)"),
}  # fmt: skip


@dataclass(frozen=True)
class Recorded:
    """Constants the delivery manager records before commit (spec section 1.2, open points
    1-4). ``None`` is "not recorded": the script refuses to start."""

    #: File name of each poster file inside ``--poster-dir`` (RUL 3.1, T1).
    file_names: Mapping[str, str | None]
    #: Full sha256 of each poster file (RUL T1; only truncated forms are in the ruling).
    file_sha256: Mapping[str, str | None]
    #: The 48 standing run ids (REG 1043), from the delivery manager's slot-free run ledger,
    #: which was built from the run ids in the poster's out files. T4 holds the out files to
    #: that ledger (a consistency test, not an independent one); tests (a), (b) and campaign
    #: membership check each id against the product.
    standing_ids: frozenset[str] | None
    #: T7: how the place in an out-file key is formed. Recorded as "slot": the poster writes
    #: the key ``f"{name}/{r['slot']}"`` (``wave4_post.py`` line 130). The plan parser reads
    #: the slot rule only, so any other value is not ready.
    place_rule: str | None


#: STANDING_IDS: the 48 standing run ids, from the delivery manager's slot-free run ledger
#: of 2026-11-12 (sorted by run id; sha256 of the id list, one id per line,
#: b79c3cbedaf775238e0f74ddb506a7ebb86858d9b20845ca97a65dd6a7bedf3d). That ledger was built
#: on 2026-11-11/12 from the run ids the poster recorded, so T4 holds the out files to the
#: ledger as issued; it is test (a), against the product's own run records, that checks each
#: id independently of the poster.
STANDING_IDS: frozenset[str] = frozenset(
    {
        "011c42143bfc42f7b10216b39c54297e",
        "0599ec33db3e4426bb33e9dfb8e4d3bc",
        "05d4a664263948f9a0152f27ee1e70c2",
        "13d2ac417bde44269733dd1aec28a476",
        "220e17cd019b4def82ed1415edf9173f",
        "22e35037a101456cb05b107e6726a8d3",
        "2a8a000ccf494b9ba4b8a896dc9cee31",
        "2ad5b7fd77524ac29fc1797ac5c5b436",
        "31377ac93e1c48edb482c729ecd1962c",
        "3ed31753022c49c78d941ccdad093dce",
        "3f17a9b8fd8f4c88992d6d455e6bc8e3",
        "3f67a4d0de6344ab8a3dd84015db86ec",
        "461a453c518747859fe4c40a88ddc140",
        "52f8630ba3ae469583dabf2f43287af7",
        "54861a383be9468dac5bd11a38feb5ae",
        "5757bed0f75442c4bc4d824e1b23bbb2",
        "5a6bd92c96dd4ce3b8c15c92f3651592",
        "5a8e8e6ca713460d9316ecafbd48c954",
        "5fd4dc4053224b86a3c27103359f3575",
        "688a8a4fb25d4ff79ccfbe8480456001",
        "6e248c840587422b8058a1e35ee755c2",
        "76df3cb7e5374fe38ea40e73afc7d31b",
        "78b4d435c1ef4437b2e4dcfd333840d6",
        "7f3ee062cf5a4fd4a96c0936de69ad1e",
        "8a258976d0d341baaf3196b3d27545aa",
        "8f376716f5644484ab07e5ba25e23b7a",
        "a2373f8815c843548c5e4529334866b0",
        "a774c29e33ec4b23bf1776309c5ee534",
        "abcf240a01f64c4c85b49a4c9feb2bb1",
        "ae14ae16550c47d29dee66954b9c7c42",
        "b49c2e6a85914cc2982d888bf30a2318",
        "b560dc5dd5d5471594da65c0e9d4dae2",
        "b93cb250772b4ff094636a02310c940d",
        "c01474469e7c44bc96d0b8ccb0c49de4",
        "c98ee5ba4b904b90a56a18c806dba887",
        "ccb5788dd1f7450bbbb6c6a105f814d7",
        "d768fea1d0954ed48def2cba0861a216",
        "dc085b5a74d04e8ea7f1d860e3a131e8",
        "df6fba6c7d7f4b4b88b838cbd464736f",
        "e29c211744e74c84a7aa0e6867edf18f",
        "e2b449d55f424ed7bb22003e0b4f4a6e",
        "e8b9bf2b8f0d477992b6fb41af118bea",
        "e8e9638912e1460cacf225c4f6719a8c",
        "e9fb1e26078a4e48a4aeddff721fd176",
        "ed819b4e863749899c74924401ad1382",
        "f24c842e94284f5e98912df45efd5fac",
        "f2aaae197a4f40eb87b3d4ec2f48b323",
        "ff18647e6afe42eb9e9af2c00d998c25",
    }
)
#: sha256 of the id list, sorted, one id per line ("".join(i + "\n" for i in sorted(ids))).
STANDING_IDS_SHA256 = "b79c3cbedaf775238e0f74ddb506a7ebb86858d9b20845ca97a65dd6a7bedf3d"
STANDING_PROVENANCE = (
    "Standing ids: from the slot-free run ledger (built from the poster's out files); "
    "id-list sha256 {sha}; T4 is a consistency test."
)
NO_RECORD_READ = "No run record was read. No run id and no time is concerned."
#: The keys of an out-file entry and of its ``run`` object (``wave4_post.py`` lines 83-95,
#: 150-157): compared by name only, no value read.
OUT_ENTRY_KEYS = frozenset({"arm", "posted", "run", "ended", "clean_end"})
OUT_RUN_KEYS = frozenset({
    "id", "status", "progress", "clean", "errors", "stopped_reason", "stopped_code",
    "cost_usd", "error",
})  # fmt: skip

#: Recorded by the delivery manager from the poster's source text ``wave4_post.py`` (sha256
#: b30ca68ea35e7659b720011af690c6cc3713dfd8f6ce1777523f4651b850b105): the plan file name
#: (line 102), the out file names (lines 150-157 and 169), the place rule (line 130). The full
#: hashes agree with the ruling's truncated T1 forms (checked by ``check_ready``).
RECORDED = Recorded(
    file_names={
        "plan": "wave-batches.json",
        "pre_s3": "wave-batches.before-s3.json",
        "click_out": "click-out.json",
        "cobra_out": "cobra-out.json",
    },
    file_sha256={
        "plan": "ae705b68e03e1ff58972d34cdb81f5e85095ca88449e23a99a9c5276702fb45a",
        "pre_s3": "a3c592cd9e7a19210888b2f9bd6d3b8c6e05d6ce76169e996a71d36d7b2970fd",
        "click_out": "27b2747e044048c6766186a1689cc5749178c46a8dce3c78dacd6ed09a4c4170",
        "cobra_out": "59d7eefc3361caa5f78fd18bc8b66f5e0e2cc5f36a1e49915ea79033b506e0e1",
    },
    standing_ids=STANDING_IDS,
    place_rule="slot",
)

HEX32 = re.compile(r"\A[0-9a-f]{32}\Z")  # \Z: a trailing newline is not a run id
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ABSENT: Any = object()

# ---------------------------------------------------------------------------
# errors and output
# ---------------------------------------------------------------------------


class NotReadyError(Exception):
    """Exit 1: a constant, argument or the login file is not as required; no request."""


class ShapeError(Exception):
    """A parsed document is not of the recorded shape. The message names no value."""


class TransportError(Exception):
    """A request was not answered as expected. The message names no response value."""


class Out:
    """Writes each stdout line to the stream as soon as it is made, and the same line to the
    ``--output`` file once it is attached. Lines made before the file is opened are held and
    written to it first, so the file is the stdout text byte for byte."""

    def __init__(self, stream: Any) -> None:
        self.stream = stream
        self.file: Any = None
        self.held: list[str] = []

    def attach(self, file: Any) -> None:
        self.file = file
        for text in self.held:
            file.write(text)
        file.flush()
        self.held.clear()

    def line(self, text: str = "") -> None:
        text += "\n"
        self.stream.write(text)
        self.stream.flush()
        if self.file is None:
            self.held.append(text)
        else:
            self.file.write(text)
            self.file.flush()

    def close(self) -> None:
        if self.file is not None:
            self.file.close()


# ---------------------------------------------------------------------------
# strict JSON and JSON equality
# ---------------------------------------------------------------------------


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in pairs:
        if k in out:
            raise ShapeError("duplicate object key")
        out[k] = v
    return out


def _no_constant(_name: str) -> Any:
    raise ShapeError("NaN or Infinity in JSON")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ShapeError("number out of range in JSON")
    return value


def strict_json(data: bytes) -> Any:
    """Parse UTF-8 JSON, refusing duplicate keys, NaN/Infinity, a number that overflows a
    float (``1e999``), an integer too long to convert and nesting too deep to parse."""
    try:
        text = data.decode("utf-8")
        return json.loads(
            text, object_pairs_hook=_pairs_no_duplicates, parse_constant=_no_constant,
            parse_float=_finite_float,
        )  # fmt: skip
    except ShapeError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ShapeError("not JSON") from exc


def is_number(x: Any) -> bool:
    """A JSON number: int or float, never bool (RUL section 4)."""
    return isinstance(x, int | float) and not isinstance(x, bool)


def is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def num_equal(a: Any, b: Any) -> bool:
    """Two JSON numbers are equal as exact numbers; a non-finite float equals nothing."""
    if not (is_number(a) and is_number(b)):
        return False
    if any(isinstance(x, float) and not math.isfinite(x) for x in (a, b)):
        return False
    return Fraction(a) == Fraction(b)


def json_equal(a: Any, b: Any) -> bool:
    """RUL section 4 equality: numbers as numbers, a bool is not a number, strings exact,
    arrays element-wise in order, objects with the same key set and equal values."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if is_number(a) or is_number(b):
        return num_equal(a, b)
    if isinstance(a, str) or isinstance(b, str):
        return isinstance(a, str) and isinstance(b, str) and a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, list) or isinstance(b, list):
        return (
            isinstance(a, list)
            and isinstance(b, list)
            and len(a) == len(b)
            and all(json_equal(x, y) for x, y in zip(a, b, strict=True))
        )
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(json_equal(a[k], b[k]) for k in a)
    return False


def carried(body: Mapping[str, Any], key: str) -> bool:
    """A key is carried when present and not null (RUL section 4; REG 1068)."""
    return key in body and body[key] is not None


# ---------------------------------------------------------------------------
# readiness
# ---------------------------------------------------------------------------


def standing_ids_sha256(ids: Iterable[str]) -> str:
    """sha256 of the ids sorted, one per line (the form the ledger's hash was taken in)."""
    return hashlib.sha256("".join(i + "\n" for i in sorted(ids)).encode("utf-8")).hexdigest()


def check_ready(rec: Recorded) -> None:
    """Refuse to start on any missing or malformed recorded constant (spec 1.2)."""
    for role in FILE_ROLES:
        name = rec.file_names.get(role)
        if not isinstance(name, str) or not name or "/" in name or name in {".", ".."}:
            raise NotReadyError(f"FILE_NAMES[{role}] not recorded")
    for role in FILE_ROLES:
        full = rec.file_sha256.get(role)
        if full is None:
            raise NotReadyError(f"FILE_SHA256[{role}] not recorded")
        prefix, suffix = FILE_SHA256_TRUNCATED[role]
        if (
            not isinstance(full, str)
            or not HEX64.match(full)
            or not full.startswith(prefix)
            or not full.endswith(suffix)
        ):
            raise NotReadyError(f"FILE_SHA256[{role}] does not agree with the ruling's T1")
    ids = rec.standing_ids
    if ids is None:
        raise NotReadyError("STANDING_IDS not recorded")
    if len(ids) != 48 or not all(isinstance(i, str) and HEX32.match(i) for i in ids):
        raise NotReadyError("STANDING_IDS is not 48 full run ids")
    if standing_ids_sha256(ids) != STANDING_IDS_SHA256:
        raise NotReadyError("STANDING_IDS does not match STANDING_IDS_SHA256")
    if rec.place_rule is None:
        raise NotReadyError("PLACE_RULE not recorded")
    if rec.place_rule != "slot":
        raise NotReadyError("PLACE_RULE is not slot (wave4_post.py line 130)")
    if not (isinstance(L_VALUE, str) and L_VALUE):
        raise NotReadyError("L not recorded")


# ---------------------------------------------------------------------------
# poster files (kept: body, slot; run)
# ---------------------------------------------------------------------------


def wave_batch_name(repo: str, b: int) -> str:
    return f"{repo}-{b}"


def extract_plan(doc: Any, *, batch_may_be_absent: bool = False) -> dict[str, Any]:
    """{wave key: body} for the 48 wave keys of the plan file or its pre-S3 copy.

    A wave batch absent from the plan file is a shape failure (T3). A wave batch absent
    from the pre-S3 copy (``batch_may_be_absent``) leaves its four keys out, and T2 reports
    them: the copy then does not hold the body the plan file holds.

    The shape is the poster's (``wave4_post.py`` line 102: one top-level object keyed by batch
    name; line 127: ``batches[name]``; lines 127-130: a batch holds ``cell``, ``coin``,
    ``order`` and ``runs``, a list whose entries hold ``slot``, ``arm`` and ``body``; line 130:
    the key's place is the entry's ``slot``). Only the 12 wave batch names are looked up; any
    other batch (the ``S3`` batches added later among them) is never touched. Of a wave batch
    only ``runs`` is read, and of an entry only ``slot`` and ``body``: the poster's ``arm``
    label, ``cell``, ``coin`` and ``order`` are never read (RUL section 5). Anything else
    fails closed as a shape failure (test T3)."""
    if not isinstance(doc, dict):
        raise ShapeError("plan is not an object")
    out: dict[str, Any] = {}
    for repo, b in BATCH_KEYS:
        name = wave_batch_name(repo, b)
        if name not in doc:
            if batch_may_be_absent:
                continue
            raise ShapeError("plan lacks a wave batch")
        batch = doc[name]
        if not isinstance(batch, dict) or "runs" not in batch:
            raise ShapeError("plan batch has no runs")
        entries = batch["runs"]
        if not isinstance(entries, list) or len(entries) != 4:
            raise ShapeError("plan batch runs is not a list of four entries")
        places: dict[int, Any] = {}
        for entry in entries:
            if not isinstance(entry, dict) or "body" not in entry or "slot" not in entry:
                raise ShapeError("plan entry has no body or no slot")
            place = entry["slot"]
            if not is_int(place) or not 1 <= place <= 4 or place in places:
                raise ShapeError("plan batch slots are not the integers 1 to 4 once each")
            places[place] = entry["body"]
        for p in range(1, 5):
            out[f"{name}/{p}"] = places[p]
    return out


def extract_out(doc: Any) -> dict[str, str]:
    """{key: run id} for every key of an out file (``click-out.json``, ``cobra-out.json``).

    The shape is the poster's (``wave4_post.py`` lines 150-157 and 169: one top-level object
    keyed by ``f"{name}/{slot}"``, plus ``click-3/1#attempt1`` written by ``refile.py``; each
    entry holds ``arm``, ``posted``, ``run``, ``ended`` and ``clean_end``, and ``run`` is the
    object of ``brief()``, lines 83-95: ``id``, ``status``, ``progress``, ``clean``,
    ``errors``, ``stopped_reason``, ``stopped_code``, ``cost_usd``, ``error``). Only
    ``run.id`` is read; every other key is never read, kept or printed (RUL sections 5 and
    11). An entry with no ``run`` object (line 152: a ``refusal`` entry), or a ``run`` whose
    ``id`` is absent or not a string, fails closed as a shape failure (test T3). Whether the
    id is a full run id is test T4.

    The key names (never the values) of each entry and of its ``run`` object must be exactly
    those ``brief()`` and the poster write (``OUT_ENTRY_KEYS``, ``OUT_RUN_KEYS``); any other
    key set fails closed as a shape failure."""
    if not isinstance(doc, dict):
        raise ShapeError("out file is not an object")
    out: dict[str, str] = {}
    for key in doc:
        entry = doc[key]
        if not isinstance(entry, dict) or set(entry) != OUT_ENTRY_KEYS:
            raise ShapeError("out entry keys are not the recorded ones")
        run = entry["run"]
        if not isinstance(run, dict) or set(run) != OUT_RUN_KEYS:
            raise ShapeError("out run keys are not the recorded ones")
        rid = run["id"]
        if not isinstance(rid, str):
            raise ShapeError("out entry run id is not a string")
        out[key] = rid
    return out


# ---------------------------------------------------------------------------
# served records (kept fields only)
# ---------------------------------------------------------------------------


@dataclass
class Run:
    """A run record, kept fields only (RUL section 11). Every record keeps id, kind,
    task_ids, created and finished: the two times are not outcomes, and a failure prints
    "the run ids and times concerned" (R5 item 2), which test (b) can name outside the 49.
    ``full`` is True only for the 49 (a standing id or the resolved first filing, from the
    fixed list, never from an out file); only a full record also keeps status, counts.rows,
    the section 4 echo fields and the test (h) presence set, and only a full record counts
    as "a run record" for the 98fe708c part of (b) and for (c)/(h)."""

    id: Any
    kind: Any
    task_ids: Any
    full: bool = False
    status: Any = ABSENT
    rows: Any = ABSENT
    created: Any = ABSENT
    finished: Any = ABSENT
    repo: Any = ABSENT
    builder: Any = ABSENT
    model: Any = ABSENT
    provider: Any = ABSENT
    budget: Any = ABSENT
    max_cost_usd: Any = ABSENT
    builder_config: Any = ABSENT
    retain: Any = ABSENT
    #: Test (h): which of created/finished/status/counts.rows are present as fields.
    h_present: frozenset[str] = frozenset()


def extract_run(doc: Any, *, full: bool) -> Run:
    if not isinstance(doc, dict):
        raise ShapeError("run record is not an object")
    run = Run(
        id=doc.get("id", ABSENT), kind=doc.get("kind", ABSENT),
        task_ids=doc.get("task_ids", ABSENT), full=full,
        created=doc.get("created", ABSENT), finished=doc.get("finished", ABSENT),
    )  # fmt: skip
    if not full:
        return run
    counts = doc.get("counts")
    rows = counts.get("rows", ABSENT) if isinstance(counts, dict) else ABSENT
    present = {k for k in ("created", "finished", "status") if k in doc}
    if isinstance(counts, dict) and "rows" in counts:
        present.add("counts.rows")
    return replace(
        run,
        status=doc.get("status", ABSENT),
        rows=rows,
        repo=doc.get("repo", ABSENT),
        builder=doc.get("builder", ABSENT),
        model=doc.get("model", ABSENT),
        provider=doc.get("provider", ABSENT),
        budget=doc.get("budget", ABSENT),
        max_cost_usd=doc.get("max_cost_usd", ABSENT),
        builder_config=doc.get("builder_config", ABSENT),
        retain=doc.get("retain", ABSENT),
        h_present=frozenset(present),
    )


def extract_campaign(doc: Any) -> list[tuple[str, Any]]:
    """[(run_id, s1)] from ``runs[]``; every spend, status and total is dropped."""
    if not isinstance(doc, dict) or not isinstance(doc.get("runs"), list):
        raise ShapeError("campaign record has no run list")
    out: list[tuple[str, Any]] = []
    for item in doc["runs"]:
        if not isinstance(item, dict) or not isinstance(item.get("run_id"), str):
            raise ShapeError("campaign run has no run_id")
        out.append((item["run_id"], item.get("s1", ABSENT)))
    return out


@dataclass
class Events:
    """One run's kept events: provider values of ``author.attempt``; tasks of the two
    ``builder.author_test`` actions (``ABSENT`` when the payload's ``task`` is unreadable)."""

    providers: list[Any] = field(default_factory=list)
    started: list[Any] = field(default_factory=list)
    failed: list[Any] = field(default_factory=list)


def _payload_get(item: Mapping[str, Any], key: str) -> Any:
    payload = item.get("payload")
    if not isinstance(payload, dict) or key not in payload:
        return ABSENT
    return payload[key]


def keep_event(item: Any, ev: Events) -> int:
    """Keep the one value this event may give; return its ``seq``."""
    if not isinstance(item, dict) or not is_int(item.get("seq")):
        raise ShapeError("event without an integer seq")
    action = item.get("action")
    if action == "author.attempt":
        ev.providers.append(_payload_get(item, "provider"))
    elif action == "builder.author_test.start":
        ev.started.append(_payload_get(item, "task"))
    elif action == "builder.author_test.failed":
        ev.failed.append(_payload_get(item, "task"))
    return int(item["seq"])


@dataclass(frozen=True)
class Row:
    run_id: Any
    task_id: Any
    clean: Any
    error: Any = ABSENT


def keep_row(item: Any, *, keep_error: bool) -> Row:
    if not isinstance(item, dict):
        raise ShapeError("row is not an object")
    return Row(
        run_id=item.get("run_id", ABSENT),
        task_id=item.get("task_id", ABSENT),
        clean=item.get("clean", ABSENT),
        error=item.get("error", ABSENT) if keep_error else ABSENT,
    )


# ---------------------------------------------------------------------------
# HTTP (the only network code is in make_urllib_getter)
# ---------------------------------------------------------------------------

Getter = Callable[[str, Sequence[tuple[str, str]]], tuple[int, bytes]]
GetterFactory = Callable[[str, str, str], Getter]


def make_urllib_getter(api: str, username: str, password: str) -> Getter:
    """The default getter: signs in once with ``POST /api/v1/auth/login`` on first use, then
    answers GETs with the session cookie. No redirect is followed and nothing is retried.
    Returns (status, body); raises ``TransportError`` with a fixed message only."""
    import urllib.error  # noqa: PLC0415 - kept beside the one network function
    import urllib.parse  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    parsed = urllib.parse.urlsplit(api)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NotReadyError("api is not an http(s) URL")
    base = api.rstrip("/")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(_NoRedirect())
    cookie: list[str] = []

    def _send(req: urllib.request.Request) -> tuple[int, bytes, list[str]]:
        try:
            with opener.open(req, timeout=60) as resp:
                return resp.status, resp.read(), resp.headers.get_all("Set-Cookie") or []
        except urllib.error.HTTPError as exc:
            return exc.code, b"", []
        except Exception as exc:
            raise TransportError("connection failed") from exc

    def _login() -> None:
        body = json.dumps({"username": username, "password": password}).encode("utf-8")
        req = urllib.request.Request(  # noqa: S310 - scheme checked above
            base + "/api/v1/auth/login", data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )  # fmt: skip
        status, _resp, set_cookies = _send(req)
        if not 200 <= status < 300:
            raise TransportError(f"sign-in answered {status}")
        pairs = [c.split(";", 1)[0].strip() for c in set_cookies]
        cookie.append("; ".join(p for p in pairs if "=" in p))

    def get(path: str, query: Sequence[tuple[str, str]]) -> tuple[int, bytes]:
        if not cookie:
            _login()
        url = base + path + (("?" + urllib.parse.urlencode(list(query))) if query else "")
        req = urllib.request.Request(url, method="GET")  # noqa: S310 - scheme checked above
        req.add_unredirected_header("Cookie", cookie[0])
        status, body, _ = _send(req)
        return status, body

    return get


def get_json(get: Getter, path: str, query: Sequence[tuple[str, str]] = ()) -> Any:
    status, body = get(path, query)
    if not 200 <= status < 300:
        raise TransportError(f"GET answered {status}")
    try:
        return strict_json(body)
    except ShapeError as exc:
        raise TransportError("response is not JSON") from exc


def get_pages(get: Getter, path: str, query: Sequence[tuple[str, str]]) -> list[Any]:
    """All items of a ``Page``: ``total`` the same on every page, the items summed equal to
    it, no short page. Breaches raise ``TransportError``."""
    items: list[Any] = []
    total: int | None = None
    offset = 0
    while True:
        page = get_json(get, path, [*query, ("limit", str(PAGE_LIMIT)), ("offset", str(offset))])
        if not isinstance(page, dict) or not isinstance(page.get("items"), list):
            raise TransportError("page has no item list")
        t = page.get("total")
        if (
            not isinstance(t, int) or isinstance(t, bool) or t < 0
            or (total is not None and t != total)
        ):  # fmt: skip
            raise TransportError("page total missing or changed")
        total = t
        got = page["items"]
        if offset >= total:
            if got:
                raise TransportError("items beyond the page total")
            break
        if not got:
            raise TransportError("short page")
        items.extend(got)
        offset += len(got)
        if offset >= total:
            break
    if len(items) != total:
        raise TransportError("item count differs from the page total")
    return items


# ---------------------------------------------------------------------------
# times
# ---------------------------------------------------------------------------


def aware(value: Any) -> datetime | None:
    """A zone-aware instant, or None when absent, null, empty, unparsable or zone-less."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt


# ---------------------------------------------------------------------------
# the order check
# ---------------------------------------------------------------------------


@dataclass
class Failure:
    part: str
    reason: str
    runs: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


@dataclass
class Check:
    """The inputs of the order check and what it found."""

    rec: Recorded
    plan: dict[str, Any]
    out_click: dict[str, Any]
    out_cobra: dict[str, Any]
    campaign: list[tuple[str, Any]]
    runs: dict[str, Run]
    failures: list[Failure] = field(default_factory=list)
    not_evaluated: list[tuple[str, str]] = field(default_factory=list)
    # results
    resolved: dict[str, str] = field(default_factory=dict)
    batch_of: dict[str, tuple[str, int]] = field(default_factory=dict)
    place_of: dict[str, int] = field(default_factory=dict)
    arm_of: dict[str, str] = field(default_factory=dict)
    out: dict[str, Any] = field(default_factory=dict)

    def fail(
        self, part: str, reason: str, runs: Iterable[str] = (), lines: Iterable[str] = ()
    ) -> None:
        self.failures.append(Failure(part, reason, list(runs), list(lines)))

    def failed(self, *parts: str) -> bool:
        return any(f.part in parts for f in self.failures)

    @property
    def standing(self) -> frozenset[str]:
        assert self.rec.standing_ids is not None
        return self.rec.standing_ids

    @property
    def id98(self) -> str | None:
        return self.resolved.get(SHORT_FIRST_FILING)


def wave_keys() -> list[str]:
    return [f"{r}-{b}/{p}" for r, b in BATCH_KEYS for p in range(1, 5)]


def check_t2(plan: dict[str, Any], pre: dict[str, Any], chk_fail: Callable[..., None]) -> None:
    """RUL T2: for each of the 48 wave keys, the ``body`` in the plan file and in its copy
    from before S3 must be equal as parsed JSON. Only wave keys are compared: the S3 batches
    the plan file holds and the copy does not are never opened (RUL section 5). The plan
    file holds all 48 (``extract_plan`` fails T3 otherwise); a key whose wave batch is
    absent from the copy fails here, since the copy holds no body to be equal to."""
    lines = [
        f"key {k} (absent from the copy from before S3)" if k not in pre else f"key {k}"
        for k in wave_keys()
        if k not in pre or not json_equal(plan[k], pre[k])
    ]
    if lines:
        chk_fail("T2", "the plan file and its copy from before S3 differ", lines=sorted(lines))


def check_membership(c: Check) -> None:
    ids = [rid for rid, _ in c.campaign]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        c.fail("campaign membership", "a run is listed more than once", dup)
    non_bool = [rid for rid, s1 in c.campaign if not isinstance(s1, bool)]
    if non_bool:
        c.fail("campaign membership", "s1 is not a boolean", non_bool)
    for short in (SHORT_FIRST_FILING, *SHORT_CLICK3):
        hits = sorted({i for i in ids if i.startswith(short)})
        if len(hits) == 1:
            c.resolved[short] = hits[0]
        else:
            c.fail("(a)", f"short id {short} matches {len(hits)} runs of the campaign", hits)
    listed = set(ids)
    missing = sorted(i for i in c.standing if i not in listed)
    if missing:
        c.fail("campaign membership", "a standing run is not listed in the campaign", missing)
    if c.id98 is not None and c.id98 in c.standing:
        c.fail("campaign membership", "the first filing is among the standing ids", [c.id98])


def check_t3_t4(c: Check) -> None:
    plain = {f"{r}-{b}/{p}": r for r, b in BATCH_KEYS for p in range(1, 5)}
    expected = {**plain, ATTEMPT1_KEY: "click"}
    for repo, keys in (("click", c.out_click), ("cobra", c.out_cobra)):
        for key in keys:
            if key not in expected:
                c.fail("T3", f"key {key} is not one of the 49 keys")
            elif expected[key] != repo:
                c.fail("T3", f"key {key} is in the {repo} out file")
    both = set(c.out_click) & set(c.out_cobra)
    for key in sorted(both):
        c.fail("T3", f"key {key} is in both out files")
    union = set(c.out_click) | set(c.out_cobra)
    for key in sorted(set(expected) - union):
        c.fail("T3", f"key {key} is missing")
    if c.failed("T3"):
        return
    c.out = {k: (c.out_click if expected[k] == "click" else c.out_cobra)[k] for k in expected}

    def well_formed(v: Any) -> TypeGuard[str]:
        return isinstance(v, str) and HEX32.match(v) is not None

    # A value that is not a full run id is never printed or filed: only its key is (the
    # methodologist's reading of 2026-11-12, item 11). Run lines carry well-formed ids only.
    for key in sorted(k for k, v in c.out.items() if not well_formed(v)):
        c.fail("T4", f"the value under key {key} is not a full run id")
    vals = list(c.out.values())
    dups = sorted({v for v in vals if vals.count(v) > 1})
    if dups:
        c.fail("T4", "a run id is under more than one key", [v for v in dups if well_formed(v)])
    plain_ids = {c.out[k] for k in plain}
    if plain_ids != set(c.standing):
        c.fail(
            "T4", "the ids under the plain keys are not the 48 standing ids",
            sorted(v for v in plain_ids ^ set(c.standing) if well_formed(v)),
        )  # fmt: skip
    if c.id98 is None or c.out[ATTEMPT1_KEY] != c.id98:
        runs = [v for v in (c.out[ATTEMPT1_KEY], c.id98) if well_formed(v)]
        c.fail("T4", f"the run under {ATTEMPT1_KEY} is not the run 98fe708c resolves to", runs)


def _batch_matching(task_ids: Any) -> tuple[str, int] | None:
    if not isinstance(task_ids, list) or len(task_ids) != 5:
        return None
    if not all(isinstance(t, str) for t in task_ids) or len(set(task_ids)) != 5:
        return None
    hits = [k for k in BATCH_KEYS if set(task_ids) == set(batch_commits(*k))]
    return hits[0] if len(hits) == 1 else None


def check_a(c: Check) -> None:
    for rid in sorted(c.standing):
        r = c.runs.get(rid)
        if r is None:
            c.fail("(a)", "no run record for a standing run", [rid])
            continue
        if r.kind != "blind":
            c.fail("(a)", "kind is not blind", [rid])
        if r.status != "succeeded":
            c.fail("(a)", "status is not succeeded", [rid])
        if not (is_int(r.rows) and r.rows == 5):
            c.fail("(a)", "counts.rows is not 5", [rid])
        b = _batch_matching(r.task_ids)
        if b is None:
            c.fail("(a)", "task_ids are not the five commits of one batch", [rid])
        else:
            c.batch_of[rid] = b
    for key in BATCH_KEYS:
        members = sorted(i for i, b in c.batch_of.items() if b == key)
        if len(members) != 4:
            c.fail("(a)", f"{key[0]} batch {key[1]} has {len(members)} standing runs", members)
    want = {c.resolved[s] for s in SHORT_CLICK3 if s in c.resolved}
    if len(want) != 4 or not want <= c.standing:
        c.fail(
            "(a)", "the four runs named for click batch 3 are not four standing ids", sorted(want)
        )
    have = {i for i, b in c.batch_of.items() if b == ("click", 3)}
    if have != want:
        c.fail("(a)", "click batch 3's standing runs are not the four named", sorted(have ^ want))


def check_b(c: Check) -> None:
    x: set[str] = set()
    for rid, _ in c.campaign:
        r = c.runs.get(rid)
        if r is None:
            c.fail("(b)", "no run record for a run of the campaign", [rid])
            continue
        if not isinstance(r.kind, str):
            c.fail("(b)", "kind absent", [rid])
            continue
        if r.kind != "blind":
            continue
        t = r.task_ids
        if (
            not isinstance(t, list)
            or not t
            or any(not isinstance(i, str) or i in LISTED for i in t)
        ):
            x.add(rid)
    want = set(c.standing) | ({c.id98} if c.id98 else set())
    if x != want:
        c.fail("(b)", "the blind runs of the campaign on the listed commits are not the 49",
               sorted(x ^ want))  # fmt: skip
    id98 = c.id98
    if id98 is None:
        c.fail("(b)", "run 98fe708c does not resolve")
        return
    r = c.runs.get(id98)
    if r is None or not r.full:
        c.fail("(b)", "no run record for run 98fe708c", [id98])
        return
    if r.status != "failed":
        c.fail("(b)", "run 98fe708c status is not failed", [id98])
    if not (is_int(r.rows) and r.rows == 0):
        c.fail("(b)", "run 98fe708c counts.rows is not 0", [id98])
    if _batch_matching(r.task_ids) != ("click", 3):
        c.fail("(b)", "run 98fe708c task_ids are not click batch 3", [id98])


def the49(c: Check) -> list[str]:
    ids = sorted(c.standing)
    if c.id98:
        ids.append(c.id98)
    return ids


def check_c_h(c: Check) -> None:
    for rid in the49(c):
        r = c.runs.get(rid)
        if r is None or not r.full:
            c.fail("(h)", "no run record", [rid])
            continue
        missing = [
            f for f in ("created", "finished", "status", "counts.rows") if f not in r.h_present
        ]
        if missing:
            c.fail("(h)", "the record holds no field " + ", ".join(missing), [rid])
        if aware(r.created) is None or aware(r.finished) is None:
            c.fail("(c)", "a time is absent, null, unparsable or without a zone", [rid])


def check_d(c: Check) -> None:
    for key in BATCH_KEYS:
        members = [i for i, b in c.batch_of.items() if b == key]
        times = {i: aware(c.runs[i].created) for i in members}
        if len(set(times.values())) != 4:
            c.fail("(d)", f"two equal filing times in {key[0]} batch {key[1]}", sorted(members))
            continue
        known = {i: t for i, t in times.items() if t is not None}  # (c) passed: all known
        for place, rid in enumerate(sorted(members, key=lambda i: known[i]), start=1):
            c.place_of[rid] = place


def at(c: Check, repo: str, b: int, p: int) -> str:
    return next(i for i, k in c.batch_of.items() if k == (repo, b) and c.place_of[i] == p)


def check_t5(c: Check) -> None:
    for repo, b in BATCH_KEYS:
        for p in range(1, 5):
            key = f"{repo}-{b}/{p}"
            rid = c.out[key]
            r = c.runs[rid]
            if c.batch_of.get(rid) != (repo, b):
                c.fail("T5", f"the run under {key} holds another batch's task_ids", [rid])
            if r.repo != repo:
                c.fail("T5", f"the run under {key} is not a {repo} run", [rid])
            if c.place_of.get(rid) != p:
                c.fail("T5", f"the run under {key} is not in place {p} by filing time", [rid])
    _check_id98_times(c, "T5")


def _check_id98_times(c: Check, part: str) -> None:
    id98 = c.id98
    assert id98 is not None
    r = c.runs[id98]
    c2p4, c3p1 = at(c, "click", 2, 4), at(c, "click", 3, 1)
    created, finished = aware(r.created), aware(r.finished)
    assert created is not None and finished is not None
    end_c2 = aware(c.runs[c2p4].finished)
    start_c3 = aware(c.runs[c3p1].created)
    assert end_c2 is not None and start_c3 is not None
    if created < end_c2:
        c.fail(part, "run 98fe708c was filed before click batch 2 ended", [id98, c2p4])
    if finished > start_c3:
        c.fail(part, "run 98fe708c ended after click batch 3 place 1 was filed", [id98, c3p1])


SECTION4_KEYS = frozenset({
    "repo", "kind", "task_ids", "builder", "model", "provider", "max_cost_usd", "budget",
    "builder_config", "retain", "campaign_id", "env_stop", "outage_stop", "learning", "arm",
    "test_author",
})  # fmt: skip


def body_of(c: Check, rid: str) -> tuple[str, Any]:
    key = next(k for k, v in c.out.items() if v == rid)
    plan_key = ATTEMPT1_PLAN_KEY if key == ATTEMPT1_KEY else key
    return plan_key, c.plan.get(plan_key, ABSENT)


def check_section4(c: Check) -> None:
    for rid in the49(c):
        plan_key, body = body_of(c, rid)
        r = c.runs[rid]
        if not isinstance(body, dict):
            c.fail("section 4", f"the body under {plan_key} is not an object", [rid])
            continue
        for k in sorted(body):
            if carried(body, k) and k not in SECTION4_KEYS:
                c.fail("section 4", f"key {k} not in the field table", [rid])
        for k in ("repo", "builder", "model", "provider"):
            if carried(body, k):
                v, s = body[k], getattr(r, k)
                if not (isinstance(v, str) and isinstance(s, str) and v == s):
                    c.fail("section 4", f"{k} differs from the run record", [rid])
        if carried(body, "kind") and not (
            body["kind"] == "blind" and r.kind == "blind" and isinstance(body["kind"], str)
        ):
            c.fail("section 4", "kind differs from the run record or is not blind", [rid])
        if carried(body, "task_ids"):
            v, s = body["task_ids"], r.task_ids
            if not (
                isinstance(v, list) and isinstance(s, list) and len(v) == len(s)
                and all(isinstance(a, str) and isinstance(b, str) and a == b
                        for a, b in zip(v, s, strict=True))
            ):  # fmt: skip
                c.fail("section 4", "task_ids differ from the run record", [rid])
        if carried(body, "max_cost_usd"):
            v, s = body["max_cost_usd"], r.max_cost_usd
            if not num_equal(v, s):
                c.fail("section 4", "max_cost_usd differs from the run record", [rid])
        if carried(body, "budget"):
            v, s = body["budget"], r.budget
            ok = isinstance(v, dict) and isinstance(s, dict)
            if ok:
                kept = {k: x for k, x in v.items() if x is not None}
                ok = set(kept) == set(s) and all(json_equal(kept[k], s[k]) for k in kept)
            if not ok:
                c.fail("section 4", "budget differs from the run record", [rid])
        if carried(body, "builder_config"):
            v, s = body["builder_config"], r.builder_config
            if not (isinstance(v, dict) and isinstance(s, dict) and json_equal(v, s)):
                c.fail("section 4", "builder_config differs from the run record", [rid])
        if carried(body, "retain"):
            v, s = body["retain"], r.retain
            ok = isinstance(v, dict) and isinstance(s, dict)
            if ok:
                kept = {k: x for k, x in v.items() if x is not None}
                ok = all(k in s and json_equal(kept[k], s[k]) for k in kept) and all(
                    s[k] is False for k in s if k not in kept
                )
            if not ok:
                c.fail("section 4", "retain is contradicted by the run record", [rid])
        if not (carried(body, "campaign_id") and body["campaign_id"] == CAMPAIGN_ID
                and isinstance(body["campaign_id"], str)):  # fmt: skip
            c.fail("section 4", "the body does not carry the Wave 4 campaign id", [rid])


def read_arm(body: Any) -> str | None:
    """Test (e): S1, A0, or None when the body fits neither (REG 1065-1071)."""
    if not isinstance(body, dict):
        return None
    arm = body.get("arm")
    ta = body.get("test_author")
    if isinstance(arm, str) and arm == "S1" and isinstance(ta, str) and ta == L_VALUE:
        return "S1"
    if (arm is None or (isinstance(arm, str) and arm == "A0")) and ta is None:
        return "A0"
    return None


def check_e_arms(c: Check) -> None:
    for rid in the49(c):
        _, body = body_of(c, rid)
        arm = read_arm(body)
        if arm is None:
            c.fail("(e)", "body fits neither arm", [rid])
        else:
            c.arm_of[rid] = arm


def check_e_places(c: Check) -> None:
    for rid in sorted(c.standing):
        if rid not in c.arm_of:
            continue
        want = ORDERS[c.batch_of[rid]][c.place_of[rid] - 1]
        if c.arm_of[rid] != want:
            c.fail("(e)", "body does not give the arm its place requires", [rid])
    id98 = c.id98
    if id98 in c.arm_of and c.arm_of[id98] != ORDERS[("click", 3)][0]:
        c.fail("(e)", "body does not give the arm its place requires", [id98])


def check_s1(c: Check) -> None:
    flags = dict(c.campaign)
    for rid in the49(c):
        if rid not in c.arm_of:
            continue
        s1 = flags.get(rid, ABSENT)
        want = c.arm_of[rid] == "S1"
        if not (isinstance(s1, bool) and s1 is want):
            c.fail("campaign s1", "the campaign's s1 flag disagrees with the body", [rid])


def check_f_g(c: Check) -> None:
    def fin(i: str) -> datetime:
        v = aware(c.runs[i].finished)
        assert v is not None
        return v

    def cre(i: str) -> datetime:
        v = aware(c.runs[i].created)
        assert v is not None
        return v

    for repo, b in BATCH_KEYS:
        for p in range(1, 4):
            x, y = at(c, repo, b, p), at(c, repo, b, p + 1)
            if fin(x) > cre(y):
                c.fail("(f)", f"{repo} batch {b}: place {p} ended after place {p + 1} was filed",
                       [x, y])  # fmt: skip
    for repo in REPOS:
        for b in range(1, 6):
            x, y = at(c, repo, b, 4), at(c, repo, b + 1, 1)
            if fin(x) > cre(y):
                c.fail("(g)", f"{repo} batch {b} ended after batch {b + 1} was filed", [x, y])
    _check_id98_times(c, "(g)")
    x, y = at(c, "click", 6, 4), at(c, "cobra", 1, 1)
    if fin(x) > cre(y):
        c.fail("(g)", "click batch 6 ended after cobra batch 1 was filed", [x, y])


def run_order_check(c: Check) -> None:
    """Every part, in order; a part whose inputs depend on a failed part is not evaluated."""
    check_membership(c)
    check_t3_t4(c)
    if c.failed("T3", "T4") or c.id98 is None:
        dep = "T3/T4" if c.failed("T3", "T4") else "(a) short ids"
        for part in ("(a)", "(b)", "(c)", "(d)", "T5", "section 4", "(e)", "campaign s1",
                     "(f)", "(g)", "(h)"):  # fmt: skip
            c.not_evaluated.append((part, dep))
        return
    check_a(c)
    check_b(c)
    check_c_h(c)
    member_ok = not c.failed("campaign membership")
    if member_ok:
        check_section4(c)
        check_e_arms(c)
    else:
        for part in ("section 4", "(e)"):
            c.not_evaluated.append((part, "campaign membership"))
    if not (member_ok and not c.failed("(a)", "(c)", "(h)")):
        for part in ("(d)", "T5", "(e) places", "campaign s1", "(f)", "(g)"):
            c.not_evaluated.append((part, "campaign membership/(a)/(c)/(h)"))
        return
    check_d(c)
    if c.failed("(d)"):
        for part in ("T5", "(e) places", "(f)", "(g)"):
            c.not_evaluated.append((part, "(d)"))
        return
    check_t5(c)
    check_e_places(c)
    check_s1(c)
    check_f_g(c)


PART_ORDER = (
    "T1", "T2", "T3", "campaign membership", "T4", "(a)", "(b)", "(c)", "(d)", "T5",
    "section 4", "(e)", "campaign s1", "(f)", "(g)", "(h)", "request",
)  # fmt: skip


def _times(r: Run | None) -> str:
    """The two served times of a run whose record was fetched (any run the script read);
    NOT KEPT only when no record was fetched for that id."""
    if r is None:
        return "created NOT KEPT  finished NOT KEPT"
    cr = r.created if isinstance(r.created, str) else "ABSENT"
    fi = r.finished if isinstance(r.finished, str) else "ABSENT"
    return f"created {cr}  finished {fi}"


def print_failures(out: Out, c_failures: list[Failure], runs: Mapping[str, Run],
                   not_evaluated: Iterable[tuple[str, str]] = (), *,
                   before_request: bool = False) -> None:  # fmt: skip
    """Section 9: each failed part with its run ids and the two times; no figure. A stop
    made before the first request says in words that no run record was read (item 2)."""
    order = {p: i for i, p in enumerate(PART_ORDER)}
    for f in sorted(c_failures, key=lambda f: order.get(f.part, len(order))):
        out.line(f"ORDER CHECK FAILED: part {f.part}")
        out.line(f"  reason: {f.reason}")
        for ln in f.lines:
            out.line(f"  {ln}")
        for rid in f.runs:
            out.line(f"  run {rid}  {_times(runs.get(rid))}")
    for part, dep in not_evaluated:
        out.line(f"ORDER CHECK: part {part} not evaluated (depends on {dep})")
    if before_request:
        out.line(NO_RECORD_READ)
    out.line(FAIL_FOOTER)


# ---------------------------------------------------------------------------
# the read (A5-A9, R1-R4, R12)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchRead:
    repo: str
    batch: int
    diffs: tuple[int, ...]  # D_i = clean S1 rows - clean A0 rows, per listed commit
    without_usable: int  # k of 10 (R12)

    @property
    def u(self) -> int:
        return sum(self.diffs)

    @property
    def n(self) -> int:
        return len(self.diffs)

    @property
    def author_hit(self) -> bool:
        return self.without_usable >= AUTHOR_HIT_AT

    @property
    def label(self) -> str:
        return f"{self.repo}-{self.batch}"


@dataclass(frozen=True)
class Result:
    """One test and interval over units (sums of twice the difference, commit counts)."""

    units: tuple[tuple[int, int], ...]
    labels: tuple[str, ...]
    t2: int
    n: int
    m: int
    patterns: int
    d: Fraction
    se2: Fraction
    t: Fraction
    df: int

    @property
    def below(self) -> bool:
        return below_005(self.m, self.patterns)

    @property
    def upper_below_15(self) -> bool:
        return upper_end_below(self.d, self.se2, self.t)


def below_005(m: int, patterns: int) -> bool:
    """p = m / patterns is below 0.05 exactly when 20·m < patterns (A6)."""
    return 20 * m < patterns


def upper_end_below(d: Fraction, se2: Fraction, t: Fraction) -> bool:
    """d + t·SE < 0.15, without rounding: 0.15 − d > 0 and t²·SE² < (0.15 − d)²."""
    gap = FIFTEEN_POINTS - d
    return gap > 0 and t * t * se2 < gap * gap


def sign_flip_m(us: Sequence[int]) -> int:
    """The count of the 2^U sign patterns, the observed one included, whose |Σ ε·U| is at
    least |Σ U|, on integers (A6)."""
    target = abs(sum(us))
    return sum(
        1 for eps in product((1, -1), repeat=len(us))
        if abs(sum(e * u for e, u in zip(eps, us, strict=True))) >= target
    )  # fmt: skip


def compute(units: Sequence[tuple[int, int]], labels: Sequence[str]) -> Result | None:
    """The test and interval over units; None when it cannot be calculated (fewer than two
    units, or none: A8 item 5)."""
    b = len(units)
    if b < 2:
        return None
    us = [u for u, _ in units]
    n = sum(k for _, k in units)
    t2 = sum(us)
    d = Fraction(t2, 2 * n)
    q = sum((Fraction(u, 2) - k * d) ** 2 for u, k in units)
    se2 = Fraction(b, b - 1) * q / (n * n)
    return Result(
        units=tuple(units), labels=tuple(labels), t2=t2, n=n, m=sign_flip_m(us),
        patterns=2**b, d=d, se2=se2, t=Fraction(T975[b - 1]), df=b - 1,
    )  # fmt: skip


def primary_units(batches: Sequence[BatchRead]) -> tuple[list[tuple[int, int]], list[str]]:
    return [(x.u, x.n) for x in batches], [x.label for x in batches]


def block_units(batches: Sequence[BatchRead]) -> tuple[list[tuple[int, int]], list[str]]:
    """Consecutive author-hit batches within a repository form one unit (A8 item 3)."""
    units: list[tuple[int, int]] = []
    labels: list[str] = []
    prev: BatchRead | None = None
    for x in batches:
        if (
            prev is not None and x.author_hit and prev.author_hit and prev.repo == x.repo
            and x.batch == prev.batch + 1
        ):  # fmt: skip
            u, n = units[-1]
            units[-1] = (u + x.u, n + x.n)
            labels[-1] = labels[-1] + "+" + x.label
        else:
            units.append((x.u, x.n))
            labels.append(x.label)
        prev = x
    return units, labels


def leftout_units(batches: Sequence[BatchRead]) -> tuple[list[tuple[int, int]], list[str]]:
    kept = [x for x in batches if not x.author_hit]
    return [(x.u, x.n) for x in kept], [x.label for x in kept]


def sgn(x: int) -> int:
    return (x > 0) - (x < 0)


def decide(
    p: Result, k: Result | None, o: Result | None, nonzero: int, usable: int
) -> tuple[str, str]:
    """A9 in order, with R1 (direction), R3 (three signs) and R4 (six of the 12 primary
    batches). Returns (word, the condition that fixed it)."""
    for name, r in (("blocks", k), ("left-out", o)):
        if r is None:
            return "Inconclusive", f"the {name} result cannot be calculated"
        if r.below != p.below:
            return "Inconclusive", f"the {name} result falls on the other side of 0.05"
        if sgn(r.t2) != sgn(p.t2):
            return "Inconclusive", f"the {name} result has a summed difference of the other sign"
    assert k is not None and o is not None
    if all(r.below and r.t2 > 0 for r in (p, k, o)):
        return "Cleared", "p below 0.05 with S1 ahead, and both sensitivity results too"
    unmet: list[str] = []
    if any(r.below for r in (p, k, o)):
        unmet.append("p below 0.05 without S1 ahead")
    if not all(r.upper_below_15 for r in (p, k, o)):
        unmet.append("an upper end not below 15 points")
    if nonzero < SIX_BATCHES:
        unmet.append(f"{nonzero} of 12 batches with a non-zero summed difference (fewer than 6)")
    if usable < NINE_IN_TEN:
        unmet.append(f"usable tests {usable} of 120 (fewer than 108)")
    if not unmet:
        return "No 15-point effect", "every condition of item 4 holds"
    return "Inconclusive", "anything else: " + "; ".join(unmet)


def usable_attempt(row: Row | None, ev: Events, commit: str) -> bool:
    """R12 item 3: (a) a row; (b) a start for the task; (c) no failed for the task (an
    unreadable failed task makes (c) unreadable); (d) error a str not starting authoring:."""
    if row is None:
        return False
    if not any(isinstance(t, str) and t == commit for t in ev.started):
        return False
    if any(t is ABSENT or not isinstance(t, str) or t == commit for t in ev.failed):
        return False
    return isinstance(row.error, str) and not row.error.startswith(AUTHORING_PREFIX)


def build_batches(
    c: Check, rows: Mapping[str, list[Row]], events: Mapping[str, Events]
) -> list[BatchRead]:
    out: list[BatchRead] = []
    for repo, b in BATCH_KEYS:
        members = [i for i, k in c.batch_of.items() if k == (repo, b)]
        s1 = [i for i in members if c.arm_of[i] == "S1"]
        a0 = [i for i in members if c.arm_of[i] == "A0"]
        diffs: list[int] = []
        without = 0
        for commit in batch_commits(repo, b):

            def clean_count(ids: list[str], commit: str = commit) -> int:
                return sum(
                    1 for i in ids for r in rows[i] if r.task_id == commit and r.clean is True
                )

            diffs.append(clean_count(s1) - clean_count(a0))
            for i in s1:
                row = next((r for r in rows[i] if r.task_id == commit), None)
                if not usable_attempt(row, events[i], commit):
                    without += 1  # a missing row counts here too (Part 6 item 3)
        out.append(BatchRead(repo, b, tuple(diffs), without))
    return out


def fmt_points(x: Fraction) -> str:
    with localcontext() as ctx:
        ctx.prec = 50
        v = (Decimal(x.numerator) / Decimal(x.denominator)) * 100
        return str(v.quantize(Decimal("0.0001")))


def fmt_dec(x: Fraction) -> str:
    """An exact fraction as a decimal to 4 places (50-digit context)."""
    return fmt_points(x / 100)


def fmt_sqrt_points(x: Fraction) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        return (Decimal(x.numerator) / Decimal(x.denominator)).sqrt()


def interval(r: Result) -> tuple[str, str]:
    with localcontext() as ctx:
        ctx.prec = 50
        d = Decimal(r.d.numerator) / Decimal(r.d.denominator)
        half = Decimal(r.t.numerator) / Decimal(r.t.denominator) * fmt_sqrt_points(r.se2)
        q = Decimal("0.0001")
        return str(((d - half) * 100).quantize(q)), str(((d + half) * 100).quantize(q))


def exact_decimal(m: int, patterns: int) -> str:
    with localcontext() as ctx:
        ctx.prec = 60
        return format((Decimal(m) / Decimal(patterns)).normalize(), "f")


def print_result(out: Out, title: str, r: Result | None, *, show_units: bool) -> None:
    out.line(title)
    if r is None:
        out.line("  cannot be calculated")
        return
    if show_units:
        out.line("  units: " + ", ".join(r.labels))
    out.line(f"  units B = {r.patterns.bit_length() - 1}; commits N = {r.n}")
    out.line(f"  T = {Fraction(r.t2, 2)}; d = {fmt_points(r.d)} points")
    out.line(
        f"  m = {r.m} of 2^{r.patterns.bit_length() - 1} = {r.patterns}; "
        f"p = {r.m}/{r.patterns} = {exact_decimal(r.m, r.patterns)}; "
        f"below 0.05: {'yes' if r.below else 'no'}"
    )
    lo, hi = interval(r)
    out.line(f"  interval: {lo} to {hi} points (t = {T975[r.df]}, df {r.df})")
    out.line(f"  upper end below 15 points: {'yes' if r.upper_below_15 else 'no'}")


@dataclass(frozen=True)
class MissingRow:
    """A listed commit of a standing run with no row in the ledger: a miss (REG 200-202)."""

    run_id: str
    task: str
    repo: str
    batch: int
    arm: str


def missing_rows(c: Check, rows: Mapping[str, list[Row]]) -> list[MissingRow]:
    """Every listed commit of every standing run with no row, by run id then list order.
    The integrity stop has passed, so each run's rows are for distinct listed commits."""
    out: list[MissingRow] = []
    for rid in sorted(c.standing):
        repo, b = c.batch_of[rid]
        have = {r.task_id for r in rows[rid]}
        out += [MissingRow(rid, t, repo, b, c.arm_of[rid])
                for t in batch_commits(repo, b) if t not in have]  # fmt: skip
    return out


def print_read(out: Out, batches: list[BatchRead], standing: Iterable[str], rows_read: int,
               missing: Sequence[MissingRow] = ()) -> int:  # fmt: skip
    p = compute(*primary_units(batches))
    assert p is not None
    k = compute(*block_units(batches))
    o = compute(*leftout_units(batches))
    usable = 120 - sum(x.without_usable for x in batches)
    nonzero = sum(1 for x in batches if x.u != 0)
    word, why = decide(p, k, o, nonzero, usable)
    m = 240 - rows_read
    out.line(f"Rows read: {rows_read} of 240 (48 runs x 5); rows missing: {m} "
             "(each counted as a miss: row rule, part 6 item 5, A3); "
             "first filing 98fe708c: set aside unread (0 rows, A2 item 3).")  # fmt: skip
    if m > 0:
        out.line(f"A3 records that all 240 rows exist. {m} do not. This goes into the deviation "
                 "log.")  # fmt: skip
    out.line("Batches (filing order):")
    for x in batches:
        s = Fraction(x.u, 2)
        out.line(
            f"  {x.repo} batch {x.batch}: n = {x.n}; S = {s} = {fmt_dec(s)}; "
            f"without usable test {x.without_usable}/10; "
            f"author-hit {'yes' if x.author_hit else 'no'}"
        )
    print_result(out, "Primary (12 batches):", p, show_units=False)
    print_result(out, "Blocks result:", k, show_units=True)
    print_result(out, "Left-out result:", o, show_units=True)
    out.line(f"batches with a non-zero summed difference: {nonzero} of 12")
    out.line(f"usable tests: {usable} of 120 (nine in ten = 108)")
    out.line(f"DECISION: {word} ({why})")
    for sentence in FIXED_SENTENCES:
        out.line(sentence)
    if missing:  # after the decision word, so nothing by arm comes ahead of the result
        out.line("Missing rows, each counted as a miss (REG 200-202):")
        for mr in missing:
            out.line(f"  run {mr.run_id}  task {mr.task}  {mr.repo} batch {mr.batch}  arm {mr.arm}")
    out.line("Stop (b), as recorded in Amendment 3 Part D (not computed by this script):")
    out.line("  strict reading: 0")
    out.line("  git stash only (the count the methodologist signs): 2")
    out.line("  every refused read-only git command: 4")
    out.line("  " + STOP_B_SENTENCE)
    out.line("Standing run ids (sorted by id; no place, no arm):")
    for rid in sorted(standing):
        out.line(f"  {rid}")
    return 0


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # exit 1, not argparse's 2 (2 is test (i))
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: {message}\n")
        raise SystemExit(1)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = _Parser(prog=SCRIPT_NAME, description="Wave 4 primary read (R5).")
    ap.add_argument("--poster-dir", required=True, help="folder holding the poster's files")
    ap.add_argument("--login", required=True, help="JSON file {username, password}")
    ap.add_argument("--api", required=True, help="base URL of the served product")
    ap.add_argument("--campaign", required=True, help="the Wave 4 campaign id")
    ap.add_argument("--deviation-out", required=True,
                    help="new file (0600) for run ids that may not be printed")  # fmt: skip
    ap.add_argument("--output", required=True,
                    help="new file (0600) that receives every stdout line")  # fmt: skip
    return ap.parse_args(argv)


def _read_file(path: str) -> bytes:
    return Path(path).read_bytes()


def _open_output(path: str) -> Any:
    """A new file, 0600, refused if it exists (``FileExistsError``); text, no newline
    translation, so it receives the stdout lines byte for byte."""
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8", newline="")


def _write_deviation(path: str, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


#: The --api check made before any file is read; the default getter checks again.
API_URL = re.compile(r"\Ahttps?://[^/?#\s@]+(/[^?#\s]*)?\Z")


def parse_login(data: bytes) -> tuple[str, str]:
    try:
        doc = strict_json(data)
    except ShapeError as exc:
        raise NotReadyError("login file shape not as expected") from exc
    if (
        not isinstance(doc, dict) or set(doc) != {"username", "password"}
        or not all(isinstance(doc[k], str) and doc[k] for k in doc)
    ):  # fmt: skip
        raise NotReadyError("login file shape not as expected")
    return doc["username"], doc["password"]


def _read_login(read_file: Callable[[str], bytes], path: str) -> tuple[str, str]:
    try:
        data = read_file(path)
    except OSError:
        raise NotReadyError("login file not readable") from None
    return parse_login(data)


def main(
    argv: Sequence[str] | None = None,
    *,
    read_file: Callable[[str], bytes] = _read_file,
    open_getter: GetterFactory = make_urllib_getter,
    write_deviation: Callable[[str, str], None] = _write_deviation,
    open_output: Callable[[str], Any] = _open_output,
    path_exists: Callable[[str], bool] = os.path.lexists,
    stdout: Any = None,
    recorded: Recorded | None = None,
    self_bytes: bytes | None = None,
) -> int:
    out = Out(stdout if stdout is not None else sys.stdout)
    try:
        return _main(argv, out, read_file=read_file, open_getter=open_getter,
                     write_deviation=write_deviation, open_output=open_output,
                     path_exists=path_exists, recorded=recorded, self_bytes=self_bytes)  # fmt: skip
    finally:
        out.close()


def _main(
    argv: Sequence[str] | None,
    out: Out,
    *,
    read_file: Callable[[str], bytes],
    open_getter: GetterFactory,
    write_deviation: Callable[[str, str], None],
    open_output: Callable[[str], Any],
    path_exists: Callable[[str], bool],
    recorded: Recorded | None,
    self_bytes: bytes | None,
) -> int:
    rec = recorded if recorded is not None else RECORDED
    args = parse_args(argv)
    own = self_bytes if self_bytes is not None else Path(__file__).read_bytes()
    out.line(f"{SCRIPT_NAME} sha256 {hashlib.sha256(own).hexdigest()}")
    out.line(f"campaign: {CAMPAIGN_ID}")
    try:
        check_ready(rec)
        if args.campaign != CAMPAIGN_ID:
            raise NotReadyError("campaign is not the registered Wave 4 campaign id")
        if path_exists(args.deviation_out):
            raise NotReadyError("deviation-out already exists")
        if os.path.abspath(args.output) == os.path.abspath(args.deviation_out):
            raise NotReadyError("output and deviation-out name the same file")
        if not API_URL.match(args.api):
            raise NotReadyError("api is not an http(s) URL")
        username, password = _read_login(read_file, args.login)
        # The output file is opened last, before any poster file is read or any request is
        # made; the lines printed so far are written to it first.
        try:
            out.attach(open_output(args.output))
        except FileExistsError:
            raise NotReadyError("output file already exists (--output)") from None
        except OSError:
            raise NotReadyError("output file cannot be created (--output)") from None
    except NotReadyError as exc:
        out.line(f"not ready: {exc}")
        return 1

    # --- T1: the four files, fixed by hash (full-string equality) ---
    paths = {role: os.path.join(args.poster_dir, str(rec.file_names[role])) for role in FILE_ROLES}
    data: dict[str, bytes] = {}
    t1: list[Failure] = []
    for role in FILE_ROLES:
        try:
            data[role] = read_file(paths[role])
        except OSError:
            t1.append(Failure("T1", "file not readable", lines=[f"file {role}"]))
            continue
        digest = hashlib.sha256(data[role]).hexdigest()
        out.line(f"input {role}: {paths[role]} sha256 {digest}")
        if digest != rec.file_sha256[role]:
            t1.append(Failure("T1", "file hash differs from the recorded one", lines=[
                f"{paths[role]}: computed {digest}, recorded {rec.file_sha256[role]}"
            ]))  # fmt: skip
    if t1:
        print_failures(out, t1, {}, before_request=True)
        return 2

    # --- parse (T3 on shape), T2 ---
    try:
        plan = extract_plan(strict_json(data["plan"]))
        pre = extract_plan(strict_json(data["pre_s3"]), batch_may_be_absent=True)
        out_click = extract_out(strict_json(data["click_out"]))
        out_cobra = extract_out(strict_json(data["cobra_out"]))
    except ShapeError:
        print_failures(out, [Failure("T3", "file shape not as recorded")], {}, before_request=True)
        return 2
    del data
    pre_fail: list[Failure] = []
    check_t2(plan, pre, lambda part, reason, lines=(): pre_fail.append(
        Failure(part, reason, [], list(lines))))  # fmt: skip
    del pre
    if pre_fail:  # T2 failed: stop before any request (RUL 3.2; test (i))
        print_failures(out, pre_fail, {}, before_request=True)
        return 2

    # --- E2, E3: the campaign's runs and their records ---
    get = open_getter(args.api, username, password)
    runs: dict[str, Run] = {}
    current: list[str] = []  # the run whose record is being requested, for the failure
    try:
        campaign = extract_campaign(get_json(get, f"/api/v1/campaigns/{CAMPAIGN_ID}"))
        # K5: the 49 kept in full (status, row count, echo fields; times are kept for every
        # record) come from the fixed list (the standing ids and the first filing as resolved
        # from the campaign), never from an out-file value.
        hits = {i for i, _ in campaign if i.startswith(SHORT_FIRST_FILING)}
        full_ids = set(rec.standing_ids or ()) | (hits if len(hits) == 1 else set())
        for rid, _ in campaign:
            if rid in runs:
                continue
            if not HEX32.match(rid):
                raise TransportError("a campaign run id is not a full run id")
            current[:] = [rid]
            runs[rid] = extract_run(get_json(get, f"/api/v1/runs/{rid}"), full=rid in full_ids)
            if runs[rid].id != rid:
                raise TransportError("a run record names another id")
            current.clear()
    except (TransportError, ShapeError) as exc:
        print_failures(out, [Failure("request", f"order-check request: {exc}", current)], runs)
        return 2

    chk = Check(rec=rec, plan=plan, out_click=out_click, out_cobra=out_cobra,
                campaign=campaign, runs=runs, failures=[])  # fmt: skip
    run_order_check(chk)
    if chk.failures or chk.not_evaluated:
        print_failures(out, chk.failures, runs, chk.not_evaluated)
        return 2

    # --- order check passed (RUL 3.3, section 11) ---
    for name, fld in H_FIELDS:
        out.line(f"{name}: {fld}")
    out.line(f"L = {L_VALUE} (source: {L_SOURCE})")
    for role in FILE_ROLES:
        out.line(f"file {role}: {paths[role]} sha256 {rec.file_sha256[role]}")
    out.line("Taken on trust")
    for i, text in enumerate(TRUST_LINES, start=1):
        out.line(f"{i}. {text}")
    out.line("Not compared (not served): env_stop, outage_stop, learning.")
    out.line("Order check passed.")
    out.line(S1_FLAG_SENTENCE)
    out.line(STANDING_PROVENANCE.format(sha=STANDING_IDS_SHA256))

    # --- E4: events of the 24 standing S1 runs; the provider test (Amendment 4 point 4) ---
    s1_runs = sorted(i for i in chk.standing if chk.arm_of[i] == "S1")
    events: dict[str, Events] = {}
    failed: list[str] = []  # the run whose events were being read (K8)
    try:
        for rid in s1_runs:
            failed[:] = [rid]
            ev = Events()
            last = None
            for item in get_pages(get, f"/api/v1/runs/{rid}/events/log", []):
                seq = keep_event(item, ev)
                if last is not None and seq <= last:
                    raise TransportError("event seq not increasing")
                last = seq
            events[rid] = ev
        failed.clear()
    except (TransportError, ShapeError) as exc:
        out.line(f"read not made: E4 {exc}")
        _deviation(out, write_deviation, args.deviation_out, "E4",
                   [(r, f"not read  {_times(runs.get(r))}") for r in failed])  # fmt: skip
        return 4
    no_event = [r for r in s1_runs if not events[r].providers]
    other = [
        r
        for r in s1_runs
        if events[r].providers
        and any(not (isinstance(p, str) and p == "cerebras") for p in events[r].providers)
    ]
    if no_event or other:
        out.line(PROVIDER_STOP_LINES[0])
        out.line(PROVIDER_STOP_LINES[1].format(n1=len(no_event)))
        out.line(PROVIDER_STOP_LINES[2].format(n2=len(other)))
        _deviation(
            out,
            write_deviation,
            args.deviation_out,
            "provider test",
            [(r, f"no event  {_times(runs.get(r))}") for r in no_event]
            + [(r, f"other value  {_times(runs.get(r))}") for r in other],
        )
        return 3
    out.line(f"test author provider shown as cerebras: {len(s1_runs)} of {len(s1_runs)} "
             "standing S1 runs")  # fmt: skip

    # --- E5: the 48 runs' ledger rows; integrity ---
    rows: dict[str, list[Row]] = {}
    try:
        for rid in sorted(chk.standing):
            items = get_pages(get, "/api/v1/grades", [("run_id", rid)])
            rows[rid] = [keep_row(i, keep_error=chk.arm_of[rid] == "S1") for i in items]
    except (TransportError, ShapeError) as exc:
        out.line(f"read not made: E5 {exc}")
        _deviation(
            out,
            write_deviation,
            args.deviation_out,
            "E5",
            [
                (r, f"not read  {_times(runs.get(r))}")
                for r in sorted(chk.standing)
                if r not in rows
            ],
        )
        return 4

    # A missing row is a miss (A3; Part 6 item 3) and is scored as one in build_batches.
    # ADDED INTEGRITY STOP (not in the registered text; for the methodologist's reading): a
    # row naming another run, a task outside the run's listed commits, a second row for one
    # commit, or a non-boolean clean cannot be scored without choosing a row, so the script
    # stops rather than choose.
    def row_set_bad(r: str) -> bool:
        listed = batch_commits(*chk.batch_of[r])
        tasks = [x.task_id for x in rows[r]]
        return (
            any(not (isinstance(x.run_id, str) and x.run_id == r) for x in rows[r])
            or any(not (isinstance(t, str) and t in listed) for t in tasks)
            or len(set(tasks)) != len(tasks)
        )

    bad_set = [r for r in sorted(chk.standing) if row_set_bad(r)]
    bad_clean = [(r, x) for r in sorted(chk.standing) for x in rows[r]
                 if not isinstance(x.clean, bool)]  # fmt: skip
    if bad_set or bad_clean:
        out.line("read not made: rows not as the run records state (added integrity stop)")
        out.line(f"runs with a row for another run, an unlisted commit or one commit twice: "
                 f"{len(bad_set)}")  # fmt: skip
        out.line(f"rows with a non-boolean clean: {len(bad_clean)}")
        _deviation(
            out,
            write_deviation,
            args.deviation_out,
            "row integrity",
            [(r, f"row set  {_times(runs.get(r))}") for r in bad_set]
            + [
                (r, f"non-boolean clean  {_times(runs.get(r))}")
                for r in sorted({r for r, _ in bad_clean})
            ],
        )
        return 4

    rows_read = sum(len(v) for v in rows.values())
    return print_read(
        out, build_batches(chk, rows, events), chk.standing, rows_read, missing_rows(chk, rows)
    )


#: Printed (stdout and --output) when the deviation file cannot be created or written at a
#: stop: no traceback and no path; the stop keeps its own exit code.
DEVIATION_NOT_WRITTEN = "deviation file could not be written (--deviation-out)"


def _deviation(out: Out, write: Callable[[str, str], None], path: str, stop: str,
               items: list[tuple[str, str]]) -> None:  # fmt: skip
    text = f"{SCRIPT_NAME} stop: {stop}\n" + "".join(f"{r} {why}\n" for r, why in items)
    try:
        write(path, text)
    except OSError:
        out.line(DEVIATION_NOT_WRITTEN)


if __name__ == "__main__":
    sys.exit(main())
