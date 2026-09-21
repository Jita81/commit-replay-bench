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
// `--count` and a bool flag `--verbose`, and installs a help function on root
// that records the command and args it is invoked with. When runnable is
// false, sub has no Run (the exact program from the issue report).
func newHelpArgsRoot(f *helpArgsFixture, runnable bool) (root, sub *Command) {
	root = &Command{Use: "root"}
	sub = &Command{Use: "sub"}
	if runnable {
		sub.Run = func(*Command, []string) { f.subRuns++ }
	}
	sub.Flags().Int("count", 0, "an int flag of sub")
	sub.Flags().Bool("verbose", false, "a bool flag of sub")
	root.AddCommand(sub)
	root.SetHelpFunc(func(c *Command, args []string) {
		f.calls = append(f.calls, helpFuncCall{cmdName: c.Name(), args: args})
	})
	return root, sub
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
