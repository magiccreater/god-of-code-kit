# Assign a coding task from WSL

Install the two repositories side by side in the WSL Linux filesystem. From the kit, run `bash setup-wsl.sh` once. The machine-installed `god` command also works from projects that have no kit files yet. The kit's Python worker runs in Docker and needs no Codex CLI installation, OpenAI key, or Codex login.

```bash
god doctor
god self-test
cd ~/code/your-project
god task "Add pagination to the invoice list and cover empty pages" --single
god review "Review the current staged and unstaged invoice changes"
god apply RUN_ID
```

The first task or review installs the kit in private mode if needed. For a shared team install, use `god init .` explicitly. The coding run saves a binary-safe patch and a report under `~/.local/state/god-kit/RUN_ID`. Apply the task patch before asking to review the resulting working-tree diff. A read-only review can also inspect existing tracked code. Patch application checks the current files and fails on conflicting edits. No push or commit is automatic.

The default task asks the selected model whether two independent units can own disjoint files. A malformed or overlapping plan uses one developer. Each unit gets its own checkout. A final integrator sees their combined edits and is instructed to run the project's tests. `--single` skips planning for small jobs. `--parallel` also asks two read-only workers to research and design concurrently. On the free VM, model requests can queue behind each other while WSL tools run concurrently.

## Sydney AWS coding gateway

The [Limpid gateway profile](https://github.com/magiccreater/limpid-ai-dev-stack/tree/main/dev-stack-template/aws/chat-gateway) provides a Sydney CloudFormation stack and a `BaseUrl` output. Deploy it from an active AWS Free Plan project. Use `aws login` to keep temporary credentials in WSL.

```bash
aws login --profile god-of-code-kit --region ap-southeast-2
export GOD_AWS_PROFILE=god-of-code-kit
god doctor
cd ~/code/your-project
god task "Add a test for an empty invoice list" --single
god review "Review the current diff"
```

`GOD_AWS_STACK` selects a stack other than `limpid-chat-gateway`. The relay discovers the stack endpoint, signs requests from WSL, and translates the worker's local Responses messages into Chat Completions. The Python worker receives streamed results over its per-run Unix socket and executes Bash commands locally. The worker has no AWS credentials or network access of its own.

AWS requests select `private-coder` by default. When every part of the run, including files and tool output it might send, is public or synthetic, use `--public-openrouter` for a task or review. That selects `private-coder-public`. The Sydney stack must have an OpenRouter SecureString configured for this route to use `free-auto` when Bedrock is unavailable.

```bash
god task "Add a test to this public sample" --single --public-openrouter
```

Secure the WSL profile and choose the repository and route before starting a run. Private coding requires positive Sydney Bedrock quota. The relay refuses paid or expired AWS plans and rejects unsupported attachments and requests above the gateway's 64 KiB input limit. Unset `GOD_AWS_PROFILE` to return to the Oracle tunnel.

## Public coding with Sydney LiteLLM

Use the [Sydney LiteLLM stack](https://github.com/magiccreater/limpid-ai-dev-stack/tree/main/dev-stack-template/aws/litellm-router) for task-aware public model selection.

```bash
export GOD_AWS_PROFILE=god-of-code-kit
export GOD_AWS_STACK=limpid-litellm-router
god doctor
god task "Add a test to this public sample" --single --public-free
```

The WSL worker sends chat requests to LiteLLM. LiteLLM invokes Laya in Sydney, keeps private code outside the public pool, and chooses from the free providers enabled by the stack operator. Use `--public-openrouter` to permit OpenRouter only. Use these public profiles for public or synthetic prompts, code, and tool output.

## Manual Laya diagnostics

The optional [Laya pilot](https://github.com/magiccreater/limpid-ai-dev-stack/tree/main/dev-stack-template/aws/laya-decisions) uses the same temporary WSL AWS login as the coding gateway. It calls its own IAM-only Lambda and has a separate decision allowance.

```bash
export GOD_AWS_PROFILE=god-of-code-kit
god decision route --kind bugfix --scope small
god decision check --public --goal "Add a regression test for empty invoices"
```

The route command sends only the selected task type and size. It recommends a model capability (quick, deep, or review) without changing the chat model. The check command runs the test commands listed under `checks` in `.ai/decision-gate.json` before asking Laya about the current public patch. Use it only with public or synthetic code and goal text. The result is advisory and does not write a push-gate receipt. For private patches, use the existing local decision gate on loopback.

## Oracle setup

An initialized shared repository also carries its own launcher. From that project, `bash .claude/god/run.sh task "your assignment"` uses the installed worker and the existing WSL tunnel. Run `god status` to locate recent reports and patches.

1. Run `god oracle auth` in WSL. Enter your tenancy OCID, user OCID and home region at the OCI CLI prompts. Upload the generated **public PEM** under your OCI user's API keys. If you already have a DEFAULT API-key profile, keep it. This profile expects key material under `~/.oci`. Do not paste private keys in chat.
2. Run `god oracle up`. This looks up your current public IPv4 address using checkip.amazonaws.com and permits SSH from its /32. Pass `god oracle up ADDRESS/32 COMPARTMENT_OCID` to supply it yourself. The default compartment is the tenancy root. Review the Terraform plan and type `apply` to provision. Check your remaining A1, storage and networking allowance first. On capacity errors, re-run later or select another availability domain with `GOD_AD_INDEX=1 god oracle up` before the first successful launch.
3. Provisioning installs a pinned llama.cpp build and quantized model on the VM and opens the WSL tunnel. Initial compilation and model download can take time. Run `god doctor` for readiness. After a WSL restart, task startup attempts to reconnect the tunnel automatically.

## Slack notifications

Create a Slack app with an [incoming webhook](https://docs.slack.dev/messaging/sending-messages-using-incoming-webhooks/) for the channel you want. In WSL Bash, save its URL in your local config:

```bash
mkdir -p "$HOME/.config/god-kit"
read -rsp "Slack incoming webhook URL: " webhook
printf '\n'
install -m 600 /dev/null "$HOME/.config/god-kit/slack-webhook"
printf '%s\n' "$webhook" > "$HOME/.config/god-kit/slack-webhook"
unset webhook
```

`god doctor` checks the file format and permissions. A configured channel receives a notice when a coding or review run completes or fails. The notice contains the action, outcome, and run ID. Use `god status` in WSL to find the local report and patch. Slack failures produce a warning and preserve the local outcome. Delete the local webhook file to disable notices.

## Troubleshooting

| Symptom | Action |
|---|---|
| CLI or Docker missing | `god doctor` prints what it found. Run `god self-test` to exercise Docker, the Python worker and the sanitizer with synthetic Oracle and AWS responses. It builds the default worker image on first use. |
| OCI authentication fails | Check that the public PEM fingerprint, user OCID, tenancy OCID and DEFAULT profile region match. Retry `god oracle up` after uploading the public key. |
| Provisioning or deployment interrupted | Repeat `god oracle up` to reuse Terraform state. After the IP is recorded, `god oracle deploy` retries installation on that VM. Preserve `~/.local/state/god-oracle`, including its state and SSH key. |
| SSH fails after changing internet connections | Run `god oracle up` again to update your allowed source address. |
| Gateway reachable, model loading or failed | Run `god oracle logs` for both systemd units. After the model is ready, retry the task. |
| Tests need a different language or dependencies | Build an image FROM god-kit-worker:1.0.0 with the project's toolchain and dependencies baked in. Set GOD_WORKER_IMAGE to its local tag. Worker runtime has no internet or host package caches. |
| Missing project files | The snapshot includes current contents of Git-tracked regular files and local kit Markdown. Stage new files that the agent should see. Symlinks and excluded paths are skipped. Review the generated patch and test results before applying. |
| Request blocked | Keep attachments, encoded blobs and private keys out of the task. Add project-specific literals or paths to the local exclusions below. |

## Privacy and inference cost

Every worker runs inside a WSL Docker container with no external network, host credentials or Docker socket. It accesses inference through a Unix socket to the WSL sanitizer. Reviews mount the checkout read-only. Coding and review both use the selected backend. The reviewer starts with a fresh model context. A worker makes up to 12 model turns. Long command output is truncated, and commands have a five-minute timeout. Large tasks can be split into smaller assignments.

Add one literal identifier per line to `~/.config/god-kit/redact` and one repo-relative glob per line to `~/.config/god-kit/exclude`. The sanitizer also handles known credential patterns and email addresses on prompts and tool outputs. Free-form confidential facts, unfamiliar credential formats and business logic can survive pattern redaction. Local reports may contain project information.

The Oracle worker profile sends every inference request to the model on the VM. Cloud provisioning checks the active subscription and home region before planning. It stops if it cannot confirm the free subscription. Capacity and free allowances are controlled by Oracle.
