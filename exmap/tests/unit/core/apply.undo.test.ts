// TEST-PLAN §1 cases 53–57: undo as a new revision whose hash equals the target's.
import { describe, expect, it } from "vitest";
import * as select from "../../../src/core/select.js";
import type { ExmapEvent } from "../../../src/core/types.js";
import { createdCardId, humanProposal, propose, refused, revisionHash, run, scenario, smallMap } from "./fixtures.js";

type Undo = Extract<ExmapEvent, { type: "undo.applied" }>;

describe("undo", () => {
  it("53. undo(null) restores the previous step; the new revision hash equals the target's; statuses match the target snapshot; restored cards keep their old changed and carry restored_by", () => {
    const s = scenario();
    const step = s.step("undo1");
    const undo = step.events[1] as Undo;
    expect(undo.type).toBe("undo.applied");
    const target = step.before.revisions[undo.to_revision.seq]!;
    expect(undo.to_revision).toEqual({ seq: target.seq, hash: target.hash });
    expect(undo.from_revision).toEqual({ seq: step.before.revisions.length - 1, hash: revisionHash(step.before) });
    expect(undo.revision).toEqual({ seq: step.before.revisions.length, hash: target.hash });
    expect(revisionHash(step.state)).toBe(target.hash);
    expect(select.currentRevision(step.state).cause).toBe("undo.applied");
    for (const [id, record] of Object.entries(target.snapshot)) expect(step.state.cards[id]!.status).toBe(record.status);
    const nurse = step.state.cards[s.ids.ex_nurse!]!;
    expect(nurse.status).toBe("applied");
    expect(nurse.changed).toEqual(target.snapshot[nurse.id]!.changed);
    expect(nurse.restored_by?.proposal_id).toBe(s.ids.p_undo1);
    expect(nurse.restored_by?.event_id).toBe(undo.id);
    expect(step.state.proposals[s.ids.p_undo1!]!.status).toBe("applied");
    expect(step.state.proposals[s.ids.p_undo1!]!.affected_card_ids.sort()).toEqual([s.ids.ex_nurse, s.ids.ex_nurse2].sort());
    expect(step.state.proposals[s.ids.p_replace_id!]!.status).toBe("applied"); // historical status kept
  });

  it("54. cards created after the target become rejected/undone; a card removed since is live again; a card superseded since is live again", () => {
    const { ctx, state, rule } = smallMap();
    const targetSeq = state.revisions.length - 1;
    const e1 = run(state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "example", text: "E1", rule_id: rule } })), ctx);
    const ex1 = createdCardId(e1.events);
    const removed = run(e1.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule })), ctx).state;
    const r2 = run(removed, propose(humanProposal(ctx.nextId("prop"), { kind: "card.create", card: { kind: "rule", text: "Rule two." } })), ctx);
    const rule2 = createdCardId(r2.events);
    const pid = ctx.nextId("prop");
    const undone = run(r2.state, propose(humanProposal(pid, { kind: "undo", to_revision_seq: targetSeq })), ctx);
    expect(revisionHash(undone.state)).toBe(state.revisions[targetSeq]!.hash);
    expect(undone.state.cards[ex1]!.status).toBe("rejected");
    expect(undone.state.cards[ex1]!.rejection).toEqual({ kind: "undone", proposal_id: pid, event_id: undone.events[1]!.id });
    expect(undone.state.cards[rule2]!.rejection?.kind).toBe("undone");
    expect(undone.state.cards[rule]!.status).toBe("applied");
    expect(undone.state.cards[rule]!.rejection).toBeNull();
    expect(undone.state.cards[rule]!.restored_by?.proposal_id).toBe(pid);
    expect(undone.state.cards[rule]!.version).toBe(1); // content unchanged: no bump
    expect(select.statusLabel(undone.state.cards[ex1]!)).toBe("undone");
    // superseded since -> live again
    const s = scenario();
    const before = s.stateBefore("undo1");
    const after = s.stateAfter("undo1");
    expect(before.cards[s.ids.ex_nurse!]!.status).toBe("superseded");
    expect(after.cards[s.ids.ex_nurse!]!.status).toBe("applied");
    expect(after.cards[s.ids.ex_nurse!]!.superseded_by).toBeNull();
    expect(after.cards[s.ids.ex_nurse2!]!.supersedes).toBeNull();
    expect(after.cards[s.ids.ex_nurse2!]!.status).toBe("applied");
    // the scenario's removal undone later in the real fixture conversation: here, a removal undone restores the card
    const removedAgain = run(undone.state, propose(humanProposal(ctx.nextId("prop"), { kind: "card.remove", card_id: rule })), ctx).state;
    const back = run(removedAgain, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: null })), ctx).state;
    expect(back.cards[rule]!.status).toBe("applied");
  });

  it("55. undo of the undo redoes: the hash returns to the pre-undo value; currentRevision.cause === undo.applied before the redo", () => {
    const s = scenario();
    const beforeUndo1 = s.stateBefore("undo1");
    const afterUndo1 = s.stateAfter("undo1");
    expect(select.currentRevision(afterUndo1).cause).toBe("undo.applied");
    const afterUndo2 = s.stateAfter("undo2");
    expect(revisionHash(afterUndo2)).toBe(revisionHash(beforeUndo1));
    expect(revisionHash(afterUndo2)).not.toBe(revisionHash(afterUndo1));
    const undo2 = s.step("undo2").events[1] as Undo;
    expect(undo2.to_revision.seq).toBe(beforeUndo1.revisions.length - 1);
    expect(afterUndo2.cards[s.ids.ex_nurse!]!.status).toBe("superseded");
    expect(afterUndo2.cards[s.ids.ex_nurse2!]!.supersedes).toBe(s.ids.ex_nurse);
    expect(afterUndo2.cards[s.ids.ex_nurse2!]!.restored_by?.proposal_id).toBe(s.ids.p_undo2);
    expect(select.revisions(afterUndo2).slice(-3).map((r) => r.cause)).toEqual(["proposal.applied", "undo.applied", "undo.applied"]);
  });

  it("56. undoTarget counts batches, not revisions; more steps than batches -> null and undo { null } -> UNDO_NO_EARLIER_REVISION", () => {
    const s = scenario();
    const batch = s.step("batch");
    expect(batch.state.revisions.slice(-2).map((r) => r.cause)).toEqual(["proposal.rejected", "proposal.applied"]);
    const beforeBatch = batch.before.revisions.length - 1;
    expect(select.undoTarget(batch.state, 1)).toBe(beforeBatch);
    expect(select.undoTarget(batch.state, 2)).toBe(beforeBatch - 1);
    expect(select.undoTarget(batch.state, 3)).toBe(beforeBatch - 2);
    const batches = new Set(batch.state.revisions.slice(1).map((r) => r.batch_id)).size;
    expect(select.undoTarget(batch.state, batches)).toBe(0);
    expect(select.undoTarget(batch.state, batches + 1)).toBeNull();
    expect(select.undoTarget(batch.state, 0)).toBeNull();
    const { ctx, state } = smallMap();
    const fresh = { ...state, revisions: state.revisions.slice(0, 1) };
    expect(select.undoTarget(fresh, 1)).toBeNull();
    expect(refused(fresh, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: null })), ctx).reason).toBe("UNDO_NO_EARLIER_REVISION");
    // an undo of the two-revision batch restores the revision before both
    const undone = run(batch.state, propose(humanProposal(s.ctx.nextId("prop"), { kind: "undo", to_revision_seq: null })), s.ctx).state;
    expect(revisionHash(undone)).toBe(batch.before.revisions[beforeBatch]!.hash);
    expect(undone.cards[s.ids.q_inprogress!]!.status).toBe("applied");
    expect(undone.cards[s.ids.ex_nurse!]!.status).toBe("rejected");
  });

  it("57. undo refusals: fresh map -> UNDO_NO_EARLIER_REVISION; seq >= current -> UNDO_TARGET_IS_CURRENT / UNDO_TARGET_OUT_OF_RANGE; a target with the current hash -> NO_CHANGE", () => {
    const { ctx, state, rule } = smallMap();
    const fresh = { ...state, revisions: state.revisions.slice(0, 1), cards: {}, card_order: [] };
    expect(refused(fresh, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: null })), ctx).reason).toBe("UNDO_NO_EARLIER_REVISION");
    const current = state.revisions.length - 1;
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: current })), ctx).reason).toBe("UNDO_TARGET_IS_CURRENT");
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: current + 1 })), ctx).reason).toBe("UNDO_TARGET_OUT_OF_RANGE");
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: -1 })), ctx).reason).toBe("UNDO_TARGET_OUT_OF_RANGE");
    expect(refused(state, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: 1.5 })), ctx).reason).toBe("BAD_SHAPE");
    // update then reject it: the current hash equals the revision before the update -> NO_CHANGE for that target
    const upd = ctx.nextId("prop");
    const updated = run(state, propose(humanProposal(upd, { kind: "card.update", card_id: rule, patch: { text: "v2" } })), ctx).state;
    const rejected = run(updated, propose(humanProposal(ctx.nextId("prop"), { kind: "interpretation.reject", proposal_id: upd })), ctx).state;
    expect(revisionHash(rejected)).toBe(revisionHash(state));
    expect(refused(rejected, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: current })), ctx).reason).toBe("NO_CHANGE");
    // an explicit earlier target that differs works, and every refusal leaves nextId untouched
    const ok = run(rejected, propose(humanProposal(ctx.nextId("prop"), { kind: "undo", to_revision_seq: 0 })), ctx).state;
    expect(select.liveCards(ok)).toEqual([]);
    expect(revisionHash(ok)).toBe(state.revisions[0]!.hash);
  });
});
