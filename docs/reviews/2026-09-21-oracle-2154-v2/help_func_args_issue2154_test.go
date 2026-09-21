// Copyright 2013-2023 The Cobra Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package cobra

import (
	"fmt"
	"testing"
)

// helpFuncCall records one invocation of a help function set with SetHelpFunc.
type helpFuncCall struct {
	cmdName string
	args    []string
}

// helpArgsFixture records every invocation of the help function installed on
// root and every time sub's Run is executed.
type helpArgsFixture struct {
	calls   []helpFuncCall
	subRuns int
}

// newHelpArgsRoot builds `root` with a child `sub` that owns an int flag
// `--count` (shorthand `-c`) and a bool flag `--verbose` (shorthand `-v`), and
// installs a help function on root that records the command and args it is
// invoked with. When runnable is false, sub has no Run (the exact program from
// the issue report).
func newHelpArgsRoot(f *helpArgsFixture, runnable bool) (root, sub *Command) {
	root = &Command{Use: "root"}
	sub = &Command{Use: "sub"}
	if runnable {
		sub.Run = func(*Command, []string) { f.subRuns++ }
	}
	sub.Flags().IntP("count", "c", 0, "an int flag of sub")
	sub.Flags().BoolP("verbose", "v", false, "a bool flag of sub")
	root.AddCommand(sub)
	root.SetHelpFunc(func(c *Command, args []string) {
		f.calls = append(f.calls, helpFuncCall{cmdName: c.Name(), args: args})
	})
	return root, sub
}

// newHelpArgsRootNoFlagParsing is newHelpArgsRoot with DisableFlagParsing set
// on sub. With DisableFlagParsing cobra never parses sub's flags, so `-h` is
// not recognised either: a runnable sub receives the whole argument vector in
// its Run and help is never shown. The help function is therefore reached
// only when sub is not runnable (the flag.ErrHelp branch of ExecuteC) or via
// the built-in help command, and in both cases the args it must be given are
// the raw remaining args, exactly what a Run would receive.
func newHelpArgsRootNoFlagParsing(f *helpArgsFixture, runnable bool) (root, sub *Command) {
	root, sub = newHelpArgsRoot(f, runnable)
	sub.DisableFlagParsing = true
	return root, sub
}

// newHelpArgsRootWithRootFlags is newHelpArgsRoot with two persistent flags
// declared on root: a string flag `--config` and a bool flag `--vroot`
// (shorthand `-V`). Both are inherited by every command, including the
// built-in help command, so they may legitimately precede the help topic:
// `root help -V sub arg1`, `root help --config x sub arg1`.
func newHelpArgsRootWithRootFlags(f *helpArgsFixture, runnable bool) (root, sub *Command) {
	root, sub = newHelpArgsRoot(f, runnable)
	root.PersistentFlags().String("config", "", "a persistent string flag of root")
	root.PersistentFlags().BoolP("vroot", "V", false, "a persistent bool flag of root")
	return root, sub
}

// assertRootVroot checks the value root's persistent --vroot flag holds after
// Execute: the flag object is shared with every command that inherited it,
// so it reads true when any of them parsed `-V`/`--vroot`.
func assertRootVroot(t *testing.T, root *Command, want bool) {
	t.Helper()
	got, err := root.PersistentFlags().GetBool("vroot")
	if err != nil {
		t.Fatalf("reading root's --vroot: %v", err)
	}
	if got != want {
		t.Errorf("root's --vroot after Execute = %v, want %v", got, want)
	}
}

// assertRootConfig checks the value root's persistent --config flag holds
// after Execute (the same shared flag object as for --vroot).
func assertRootConfig(t *testing.T, root *Command, want string) {
	t.Helper()
	got, err := root.PersistentFlags().GetString("config")
	if err != nil {
		t.Fatalf("reading root's --config: %v", err)
	}
	if got != want {
		t.Errorf("root's --config after Execute = %q, want %q", got, want)
	}
}

func assertSingleHelpCall(t *testing.T, calls []helpFuncCall, wantCmd string, wantArgs []string) {
	t.Helper()
	if len(calls) != 1 {
		t.Fatalf("expected the help function to be called exactly once, got %d calls: %v", len(calls), calls)
	}
	got := calls[0]
	if got.cmdName != wantCmd {
		t.Errorf("help function called for command %q, want %q", got.cmdName, wantCmd)
	}
	if fmt.Sprintf("%q", got.args) != fmt.Sprintf("%q", wantArgs) {
		t.Errorf("help function args = %q, want %q", got.args, wantArgs)
	}
}

// The help function set with SetHelpFunc must receive the positional arguments
// of the command being helped (the command path, every flag and every flag
// value stripped, `--` honoured), not the raw argument vector that Execute was
// given.
// See https://github.com/spf13/cobra/issues/2154.
func TestHelpFuncReceivesPositionalArgsWithHelpFlag(t *testing.T) {
	tests := []struct {
		name     string
		argv     []string
		wantArgs []string
	}{
		{name: "help flag last", argv: []string{"sub", "arg1", "arg2", "-h"}, wantArgs: []string{"arg1", "arg2"}},
		{name: "help flag first", argv: []string{"sub", "-h", "arg1", "arg2"}, wantArgs: []string{"arg1", "arg2"}},
		{name: "long help flag with a local flag", argv: []string{"sub", "--count", "3", "arg1", "--help"}, wantArgs: []string{"arg1"}},
		{name: "local flag in flag=value form", argv: []string{"sub", "--count=3", "arg1", "-h"}, wantArgs: []string{"arg1"}},
		{name: "local bool flag", argv: []string{"sub", "--verbose", "arg1", "-h"}, wantArgs: []string{"arg1"}},
		{name: "shorthand local flag", argv: []string{"sub", "-c", "3", "arg1", "-h"}, wantArgs: []string{"arg1"}},
		{name: "shorthand local bool flag", argv: []string{"sub", "-v", "arg1", "-h"}, wantArgs: []string{"arg1"}},
		{name: "positionals after double dash", argv: []string{"sub", "-h", "arg1", "--", "-x"}, wantArgs: []string{"arg1", "-x"}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			f := &helpArgsFixture{}
			root, _ := newHelpArgsRoot(f, true)

			_, err := executeCommand(root, tc.argv...)
			if err != nil {
				t.Fatalf("Unexpected error: %v", err)
			}
			assertSingleHelpCall(t, f.calls, "sub", tc.wantArgs)
			if f.subRuns != 0 {
				t.Errorf("sub's Run executed %d times while help was requested, want 0", f.subRuns)
			}
		})
	}
}

// A command without a Run reaches the same flag.ErrHelp branch of ExecuteC,
// with or without an explicit help flag. The first case is the exact program
// from the issue report; the second pins the fix at that branch, so that the
// positionals are passed whichever way flag.ErrHelp was produced.
// See https://github.com/spf13/cobra/issues/2154.
func TestHelpFuncReceivesPositionalArgsForNonRunnableCommand(t *testing.T) {
	tests := []struct {
		name     string
		argv     []string
		wantArgs []string
	}{
		{name: "help flag", argv: []string{"sub", "arg1", "arg2", "-h"}, wantArgs: []string{"arg1", "arg2"}},
		{name: "no help flag", argv: []string{"sub", "arg1"}, wantArgs: []string{"arg1"}},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			f := &helpArgsFixture{}
			root, _ := newHelpArgsRoot(f, false)

			_, err := executeCommand(root, tc.argv...)
			if err != nil {
				t.Fatalf("Unexpected error: %v", err)
			}
			assertSingleHelpCall(t, f.calls, "sub", tc.wantArgs)
		})
	}
}

// `root help <path to command> <args...>` must invoke the help function for
// the command found at that path with the args that follow it, not with an
// empty slice, and must not leave any state behind that changes a later
// Execute on the same root.
// See https://github.com/spf13/cobra/issues/2154.
func TestHelpFuncReceivesPositionalArgsViaHelpCommand(t *testing.T) {
	t.Run("direct child", func(t *testing.T) {
		f := &helpArgsFixture{}
		root, _ := newHelpArgsRoot(f, true)

		_, err := executeCommand(root, "help", "sub", "arg1", "arg2")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		assertSingleHelpCall(t, f.calls, "sub", []string{"arg1", "arg2"})
	})

	t.Run("nested command", func(t *testing.T) {
		f := &helpArgsFixture{}
		root, sub := newHelpArgsRoot(f, true)
		sub.AddCommand(&Command{Use: "nested", Run: emptyRun})

		_, err := executeCommand(root, "help", "sub", "nested", "arg1")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		assertSingleHelpCall(t, f.calls, "nested", []string{"arg1"})
	})

	// The flags that follow the helped command belong to that command, not to
	// the help command: `root help sub --count 3 arg1` must not be rejected by
	// the help command's own flag parser ("unknown flag: --count"), and the
	// help function must receive the positionals with sub's flags and their
	// values stripped, just as `root sub --count 3 arg1 -h` does. That means
	// parsing them with sub's own flag set: shorthands (`-c 3`, `-v`, grouped
	// `-vc 3`) and the `--` terminator must be handled exactly as pflag does.
	flagCases := []struct {
		name     string
		argv     []string
		wantArgs []string
	}{
		{name: "local flag of the helped command stripped", argv: []string{"help", "sub", "--count", "3", "arg1"}, wantArgs: []string{"arg1"}},
		{name: "flag=value and bool flag of the helped command stripped", argv: []string{"help", "sub", "--count=3", "--verbose", "arg1"}, wantArgs: []string{"arg1"}},
		{name: "shorthand flag of the helped command stripped", argv: []string{"help", "sub", "-c", "3", "arg1"}, wantArgs: []string{"arg1"}},
		{name: "shorthand bool flag of the helped command stripped", argv: []string{"help", "sub", "-v", "arg1"}, wantArgs: []string{"arg1"}},
		{name: "grouped shorthand flags of the helped command stripped", argv: []string{"help", "sub", "-vc", "3", "arg1"}, wantArgs: []string{"arg1"}},
		{name: "positionals after double dash", argv: []string{"help", "sub", "arg1", "--", "-x"}, wantArgs: []string{"arg1", "-x"}},
	}
	for _, tc := range flagCases {
		t.Run(tc.name, func(t *testing.T) {
			f := &helpArgsFixture{}
			root, _ := newHelpArgsRoot(f, true)

			_, err := executeCommand(root, tc.argv...)
			if err != nil {
				t.Fatalf("Unexpected error: %v", err)
			}
			assertSingleHelpCall(t, f.calls, "sub", tc.wantArgs)
			if f.subRuns != 0 {
				t.Errorf("sub's Run executed %d times while help was requested, want 0", f.subRuns)
			}
		})
	}

	// The tokens after the command path are parsed with the helped command's
	// own flag set, not merely filtered out: after `help sub --count 7 arg1`
	// sub's --count flag holds 7 at the moment the help function runs.
	t.Run("flags parsed with the helped command's flag set", func(t *testing.T) {
		f := &helpArgsFixture{}
		root, sub := newHelpArgsRoot(f, true)
		countInCall, countErr := -1, error(nil)
		root.SetHelpFunc(func(c *Command, args []string) {
			f.calls = append(f.calls, helpFuncCall{cmdName: c.Name(), args: args})
			countInCall, countErr = c.Flags().GetInt("count")
		})

		_, err := executeCommand(root, "help", "sub", "--count", "7", "arg1")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		assertSingleHelpCall(t, f.calls, "sub", []string{"arg1"})
		if countErr != nil {
			t.Fatalf("reading sub's --count inside the help function: %v", countErr)
		}
		if countInCall != 7 {
			t.Errorf("sub's --count inside the help function = %d, want 7 (parsed with sub's flag set)", countInCall)
		}
		if n, _ := sub.Flags().GetInt("count"); n != 7 {
			t.Errorf("sub's --count after `help sub --count 7 arg1` = %d, want 7", n)
		}
		if f.subRuns != 0 {
			t.Errorf("sub's Run executed %d times while help was requested, want 0", f.subRuns)
		}
	})

	// Root's persistent flags are inherited by the help command, so they may
	// precede the topic; they are parsed as the help command's own (so root's
	// --vroot / --config read the given values afterwards) and the tokens from
	// the topic onwards still reach the helped command untouched. Two pflag
	// forms that a hand-rolled parser gets wrong are pinned as the base does
	// them: `--` before the topic ends the help command's flags (`help -- sub`
	// is help for sub), and `--config=` is the string flag set to the empty
	// string, consuming nothing after it (`help --config= sub` is help for sub
	// with root's --config == "", not help for root with --config == "sub").
	rootFlagCases := []struct {
		name       string
		argv       []string
		wantArgs   []string
		wantVroot  bool
		wantConfig string
	}{
		{name: "root's persistent bool flag before the topic", argv: []string{"help", "-V", "sub", "arg1"}, wantArgs: []string{"arg1"}, wantVroot: true},
		{name: "root's persistent string flag and its value before the topic", argv: []string{"help", "--config", "x", "sub", "arg1"}, wantArgs: []string{"arg1"}, wantConfig: "x"},
		{name: "double dash before the topic ends the help command's flags", argv: []string{"help", "--", "sub"}, wantArgs: []string{}},
		{name: "root's persistent string flag in flag= form takes the empty value", argv: []string{"help", "--config=", "sub"}, wantArgs: []string{}, wantConfig: ""},
	}
	for _, tc := range rootFlagCases {
		t.Run(tc.name, func(t *testing.T) {
			f := &helpArgsFixture{}
			root, _ := newHelpArgsRootWithRootFlags(f, true)

			_, err := executeCommand(root, tc.argv...)
			if err != nil {
				t.Fatalf("Unexpected error: %v", err)
			}
			assertSingleHelpCall(t, f.calls, "sub", tc.wantArgs)
			assertRootVroot(t, root, tc.wantVroot)
			assertRootConfig(t, root, tc.wantConfig)
			if f.subRuns != 0 {
				t.Errorf("sub's Run executed %d times while help was requested, want 0", f.subRuns)
			}
		})
	}

	// A help flag AFTER the topic belongs to the helped command, like every
	// other token after the command path: `help sub -h` is help for sub with
	// no positionals (at the base the help command parsed the `-h` as its
	// own and showed help for the help command with the raw argument vector).
	t.Run("help flag after the topic belongs to the helped command", func(t *testing.T) {
		f := &helpArgsFixture{}
		root, _ := newHelpArgsRoot(f, true)

		_, err := executeCommand(root, "help", "sub", "-h")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		assertSingleHelpCall(t, f.calls, "sub", []string{})
		if f.subRuns != 0 {
			t.Errorf("sub's Run executed %d times while help was requested, want 0", f.subRuns)
		}
	})

	t.Run("no side effect on a later execute", func(t *testing.T) {
		f := &helpArgsFixture{}
		root, _ := newHelpArgsRoot(f, true)

		_, err := executeCommand(root, "help", "sub", "arg1")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		assertSingleHelpCall(t, f.calls, "sub", []string{"arg1"})

		_, err = executeCommand(root, "sub")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		if f.subRuns != 1 {
			t.Errorf("sub's Run executed %d times after `help sub arg1`, want 1", f.subRuns)
		}
		if len(f.calls) != 1 {
			t.Errorf("help function called %d times in total, want 1 (a plain `sub` must not show help): %v", len(f.calls), f.calls)
		}
	})
}

// The built-in help command's own flags, and root's persistent flags that it
// inherits, keep their base behaviour when they precede the topic: they are
// parsed by the help command exactly as pflag does (long and shorthand forms,
// grouped shorthands, `--flag=value`, a persistent flag before the help
// flag). `root help -h`, `root help --help`, `root help --help=true`, `root
// help --help=1`, `root help -V -h`, `root help -Vh` and `root help --vroot
// --help` are all requests for help about the help command itself, reached
// through the flag.ErrHelp branch of ExecuteC, so the help function is
// invoked once for the help command with no positionals (not for root, and
// not with the raw argument vector), and root's --vroot reads true whenever
// it was given. A token that the help command does not own (`root help
// --bogus`, `root help -x`) or a value-taking flag without its value (`root
// help --config`) is still rejected by Execute with a non-nil error and no
// help call, as at the base.
// See https://github.com/spf13/cobra/issues/2154.
func TestHelpFuncForHelpCommandItself(t *testing.T) {
	tests := []struct {
		name      string
		argv      []string
		wantVroot bool
	}{
		{name: "shorthand help flag", argv: []string{"help", "-h"}},
		{name: "long help flag", argv: []string{"help", "--help"}},
		{name: "long help flag in flag=value form", argv: []string{"help", "--help=true"}},
		{name: "long help flag in flag=1 form", argv: []string{"help", "--help=1"}},
		{name: "root's persistent bool shorthand then the help shorthand", argv: []string{"help", "-V", "-h"}, wantVroot: true},
		{name: "root's persistent bool shorthand grouped with the help shorthand", argv: []string{"help", "-Vh"}, wantVroot: true},
		{name: "root's persistent bool flag then the long help flag", argv: []string{"help", "--vroot", "--help"}, wantVroot: true},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			f := &helpArgsFixture{}
			root, _ := newHelpArgsRootWithRootFlags(f, true)

			_, err := executeCommand(root, tc.argv...)
			if err != nil {
				t.Fatalf("Unexpected error: %v", err)
			}
			assertSingleHelpCall(t, f.calls, "help", []string{})
			assertRootVroot(t, root, tc.wantVroot)
			if f.subRuns != 0 {
				t.Errorf("sub's Run executed %d times on %q, want 0", f.subRuns, tc.argv)
			}
		})
	}

	// Guard (green at the base): an unknown flag given to the help command
	// itself is an error returned from Execute, not a help topic. A build
	// that hands the help command's raw argv to Find instead of parsing it
	// reaches CheckErr on the unknown flag and exits the test binary here.
	t.Run("unknown flag of the help command is an error", func(t *testing.T) {
		f := &helpArgsFixture{}
		root, _ := newHelpArgsRoot(f, true)

		_, err := executeCommand(root, "help", "--bogus")
		if err == nil {
			t.Fatalf("expected a non-nil error from Execute for `help --bogus`, got nil (help calls: %v)", f.calls)
		}
		if len(f.calls) != 0 {
			t.Errorf("help function called %d times on `help --bogus`, want 0: %v", len(f.calls), f.calls)
		}
		if f.subRuns != 0 {
			t.Errorf("sub's Run executed %d times on `help --bogus`, want 0", f.subRuns)
		}
	})

	// Guards (green at the base) on the root-flags fixture: pflag's parse
	// errors for the help command's own flags stay errors returned from
	// Execute, with the help function not invoked. A value-taking flag with
	// no value (`help --config` as the last token) and an unknown shorthand
	// (`help -x`) are exactly the inputs on which a hand-rolled parser reads
	// past the end of argv or dereferences a missing flag.
	guards := []struct {
		name string
		argv []string
	}{
		{name: "root's persistent string flag without a value is an error", argv: []string{"help", "--config"}},
		{name: "unknown shorthand flag of the help command is an error", argv: []string{"help", "-x"}},
	}
	for _, tc := range guards {
		t.Run(tc.name, func(t *testing.T) {
			f := &helpArgsFixture{}
			root, _ := newHelpArgsRootWithRootFlags(f, true)

			_, err := executeCommand(root, tc.argv...)
			if err == nil {
				t.Fatalf("expected a non-nil error from Execute for %q, got nil (help calls: %v)", tc.argv, f.calls)
			}
			if len(f.calls) != 0 {
				t.Errorf("help function called %d times on %q, want 0: %v", len(f.calls), tc.argv, f.calls)
			}
			if f.subRuns != 0 {
				t.Errorf("sub's Run executed %d times on %q, want 0", f.subRuns, tc.argv)
			}
		})
	}
}

// A command with DisableFlagParsing never has its flags parsed, so its Run
// receives the raw remaining args (see execute(): `argWoFlags = a`) and the
// help function must receive the same raw args: cmd.Flags().Args() is empty
// there and must not be used. Because `-h` is not parsed either, the help
// function is reached at the flag.ErrHelp branch of ExecuteC only for a
// non-runnable sub, whichever way the user spelled the request (the `-h` is
// then just another raw arg), and through the built-in help command for any
// sub. Both paths are pinned here.
// See https://github.com/spf13/cobra/issues/2154.
func TestHelpFuncReceivesRawArgsWithDisableFlagParsing(t *testing.T) {
	t.Run("non-runnable command", func(t *testing.T) {
		tests := []struct {
			name     string
			argv     []string
			wantArgs []string
		}{
			{name: "no help flag", argv: []string{"sub", "arg1", "--count", "3"}, wantArgs: []string{"arg1", "--count", "3"}},
			{name: "help flag first", argv: []string{"sub", "-h", "arg1", "--count", "3"}, wantArgs: []string{"-h", "arg1", "--count", "3"}},
		}
		for _, tc := range tests {
			t.Run(tc.name, func(t *testing.T) {
				f := &helpArgsFixture{}
				root, _ := newHelpArgsRootNoFlagParsing(f, false)

				_, err := executeCommand(root, tc.argv...)
				if err != nil {
					t.Fatalf("Unexpected error: %v", err)
				}
				assertSingleHelpCall(t, f.calls, "sub", tc.wantArgs)
			})
		}
	})

	t.Run("via help command", func(t *testing.T) {
		f := &helpArgsFixture{}
		root, _ := newHelpArgsRootNoFlagParsing(f, true)

		_, err := executeCommand(root, "help", "sub", "arg1", "--count", "3")
		if err != nil {
			t.Fatalf("Unexpected error: %v", err)
		}
		assertSingleHelpCall(t, f.calls, "sub", []string{"arg1", "--count", "3"})
		if f.subRuns != 0 {
			t.Errorf("sub's Run executed %d times while help was requested, want 0", f.subRuns)
		}
	})
}
