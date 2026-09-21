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
	"errors"
	"strings"
	"testing"
)

// The auto-generated "help" and "completion" sub-commands must be usable
// without the user's required persistent flags: they never consume those
// flags, so they must not fail with `required flag(s) ... not set`.
// See https://github.com/spf13/cobra/issues/1918.

const requiredFlagNotSetMsg = `required flag(s) "required" not set`

var errPreRunFailed = errors.New("root persistent pre-run failed")

// newRootWithPersistentRequiredFlag builds a fresh root command that carries a
// required persistent flag and one runnable child. A fresh tree is built for
// every check so that state left behind by one execution cannot leak into the
// next one.
func newRootWithPersistentRequiredFlag(t *testing.T) (root, child *Command) {
	t.Helper()
	root = &Command{Use: "root", Long: "Long description of root", Run: emptyRun}
	child = &Command{Use: "child", Long: "Long description of child", Run: emptyRun}
	root.AddCommand(child)
	root.PersistentFlags().Bool("required", false, "a required persistent flag")
	assertNoErr(t, root.MarkPersistentFlagRequired("required"))
	return root, child
}

func TestHelpCommandRunsWithoutPersistentRequiredFlag(t *testing.T) {
	root, _ := newRootWithPersistentRequiredFlag(t)

	output, err := executeCommand(root, "help")
	if err != nil {
		t.Fatalf("Unexpected error running `root help`: %v", err)
	}
	checkStringOmits(t, output, requiredFlagNotSetMsg)
	checkStringContains(t, output, root.Long)
	checkStringContains(t, output, "Usage:\n  root [flags]\n  root [command]")
}

func TestHelpCommandForChildRunsWithoutPersistentRequiredFlag(t *testing.T) {
	root, child := newRootWithPersistentRequiredFlag(t)

	output, err := executeCommand(root, "help", "child")
	if err != nil {
		t.Fatalf("Unexpected error running `root help child`: %v", err)
	}
	checkStringOmits(t, output, requiredFlagNotSetMsg)
	checkStringContains(t, output, child.Long)
	checkStringContains(t, output, "Usage:\n  root child [flags]")
}

func TestCompletionCommandRunsWithoutPersistentRequiredFlag(t *testing.T) {
	tests := []struct {
		shell string
		want  string
	}{
		{shell: "bash", want: "# bash completion V2 for root"},
		{shell: "zsh", want: "#compdef root"},
		{shell: "fish", want: "# fish completion for root"},
		{shell: "powershell", want: "# powershell completion for root"},
	}
	for _, tc := range tests {
		t.Run(tc.shell, func(t *testing.T) {
			root, _ := newRootWithPersistentRequiredFlag(t)

			output, err := executeCommand(root, compCmdName, tc.shell)
			if err != nil {
				t.Fatalf("Unexpected error running `root completion %s`: %v", tc.shell, err)
			}
			checkStringOmits(t, output, requiredFlagNotSetMsg)
			checkStringContains(t, output, tc.want)
			checkStringOmits(t, output, "__completeNoDesc")
		})
	}
}

func TestCompletionCommandNoDescriptionsFlagRunsWithoutPersistentRequiredFlag(t *testing.T) {
	root, _ := newRootWithPersistentRequiredFlag(t)

	// The completion sub-commands must keep parsing their own flags
	// (--no-descriptions) while ignoring the user's required persistent flag.
	output, err := executeCommand(root, compCmdName, "bash", "--no-descriptions")
	if err != nil {
		t.Fatalf("Unexpected error running `root completion bash --no-descriptions`: %v", err)
	}
	checkStringOmits(t, output, requiredFlagNotSetMsg)
	checkStringContains(t, output, "# bash completion V2 for root")
	// --no-descriptions was parsed: the script asks for descriptions-less completions.
	checkStringContains(t, output, `requestComp="${words[0]} __completeNoDesc ${args[*]}"`)
}

func TestHelpFlagOnHelpAndCompletionCommandsWithPersistentRequiredFlag(t *testing.T) {
	// `help -h` and `completion bash -h` must still show the help of the
	// sub-command itself: the fix must not disable flag parsing on them.
	root, _ := newRootWithPersistentRequiredFlag(t)
	output, err := executeCommand(root, "help", "-h")
	if err != nil {
		t.Fatalf("Unexpected error running `root help -h`: %v", err)
	}
	checkStringOmits(t, output, requiredFlagNotSetMsg)
	checkStringContains(t, output, "Help provides help for any command in the application.")
	checkStringContains(t, output, "Usage:\n  root help [command] [flags]")

	root, _ = newRootWithPersistentRequiredFlag(t)
	output, err = executeCommand(root, compCmdName, "bash", "-h")
	if err != nil {
		t.Fatalf("Unexpected error running `root completion bash -h`: %v", err)
	}
	checkStringOmits(t, output, requiredFlagNotSetMsg)
	checkStringContains(t, output, "Usage:\n  root completion bash")
	checkStringContains(t, output, "--no-descriptions")
}

func TestPersistentRequiredFlagStillEnforcedOnUserCommands(t *testing.T) {
	// Skipping the check for the built-in commands must not relax it for the
	// user's own commands.
	root, _ := newRootWithPersistentRequiredFlag(t)
	_, err := executeCommand(root, "child")
	if err == nil {
		t.Fatal("Expected `root child` to fail because --required is not set, got nil")
	}
	if err.Error() != requiredFlagNotSetMsg {
		t.Fatalf("Expected error %q, got %q", requiredFlagNotSetMsg, err.Error())
	}

	root, _ = newRootWithPersistentRequiredFlag(t)
	if _, err := executeCommand(root, "child", "--required"); err != nil {
		t.Fatalf("Unexpected error running `root child --required`: %v", err)
	}

	root, _ = newRootWithPersistentRequiredFlag(t)
	_, err = executeCommand(root)
	if err == nil {
		t.Fatal("Expected `root` to fail because --required is not set, got nil")
	}
	if err.Error() != requiredFlagNotSetMsg {
		t.Fatalf("Expected error %q, got %q", requiredFlagNotSetMsg, err.Error())
	}
}

func TestPersistentRequiredFlagEnforcedOnUserCommandsNamedLikeBuiltins(t *testing.T) {
	// The exemption applies to the command objects cobra constructs itself in
	// InitDefaultHelpCmd / InitDefaultCompletionCmd, not to any command that
	// happens to share their name. A user-defined "completion" command replaces
	// cobra's default one, a user-defined "bash" command is an ordinary
	// sub-command, and a help command supplied via SetHelpCommand is user code:
	// all three still consume the user's flags and keep required-flag
	// enforcement.
	tests := []struct {
		name  string
		setup func(root *Command)
		args  []string
	}{
		{
			name:  "user completion command",
			setup: func(root *Command) { root.AddCommand(&Command{Use: compCmdName, Run: emptyRun}) },
			args:  []string{compCmdName},
		},
		{
			name:  "user bash command",
			setup: func(root *Command) { root.AddCommand(&Command{Use: "bash", Run: emptyRun}) },
			args:  []string{"bash"},
		},
		{
			name:  "user help command via SetHelpCommand",
			setup: func(root *Command) { root.SetHelpCommand(&Command{Use: helpCommandName, Run: emptyRun}) },
			args:  []string{helpCommandName},
		},
		{
			name:  "user powershell command",
			setup: func(root *Command) { root.AddCommand(&Command{Use: "powershell", Run: emptyRun}) },
			args:  []string{"powershell"},
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			root, _ := newRootWithPersistentRequiredFlag(t)
			tc.setup(root)

			_, err := executeCommand(root, tc.args...)
			if err == nil {
				t.Fatalf("Expected `root %s` to fail because --required is not set, got nil", strings.Join(tc.args, " "))
			}
			if err.Error() != requiredFlagNotSetMsg {
				t.Fatalf("Expected error %q, got %q", requiredFlagNotSetMsg, err.Error())
			}

			root, _ = newRootWithPersistentRequiredFlag(t)
			tc.setup(root)
			if _, err := executeCommand(root, append(tc.args, "--required")...); err != nil {
				t.Fatalf("Unexpected error running `root %s --required`: %v", strings.Join(tc.args, " "), err)
			}
		})
	}
}

func TestRootPersistentPreRunStillCalledForHelpAndCompletion(t *testing.T) {
	// A CLI may rely on the root's persistent pre-run hook running for every
	// command; the built-in commands must keep honouring it.
	tests := []struct {
		args    []string
		wantCmd string // name of the command the hook must be called with
	}{
		{args: []string{"help"}, wantCmd: "help"},
		{args: []string{"help", "child"}, wantCmd: "help"},
		{args: []string{compCmdName, "bash"}, wantCmd: "bash"},
	}
	for _, tc := range tests {
		args := tc.args
		t.Run(strings.Join(args, " "), func(t *testing.T) {
			root, _ := newRootWithPersistentRequiredFlag(t)
			var calledFor []string
			root.PersistentPreRun = func(c *Command, _ []string) {
				calledFor = append(calledFor, c.Name())
			}

			output, err := executeCommand(root, args...)
			if err != nil {
				t.Fatalf("Unexpected error running `root %s`: %v", strings.Join(args, " "), err)
			}
			checkStringOmits(t, output, requiredFlagNotSetMsg)
			if len(calledFor) != 1 {
				t.Fatalf("Expected root PersistentPreRun to be called exactly once, got %d calls: %v", len(calledFor), calledFor)
			}
			if calledFor[0] != tc.wantCmd {
				t.Fatalf("Expected root PersistentPreRun to be called for %q, got %q", tc.wantCmd, calledFor[0])
			}
		})
	}

	// And a failing root PersistentPreRunE must still abort the built-in commands.
	root, _ := newRootWithPersistentRequiredFlag(t)
	root.PersistentPreRunE = func(*Command, []string) error {
		return errPreRunFailed
	}
	if _, err := executeCommand(root, "help"); err != errPreRunFailed {
		t.Fatalf("Expected `root help` to return the root PersistentPreRunE error, got %v", err)
	}
}
