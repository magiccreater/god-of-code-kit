# Assign a coding task from WSL

Install the two repositories side by side in the WSL Linux filesystem. From the kit, run `bash setup-wsl.sh` once. The machine-installed `god` command also works from projects that have no kit files yet.

```bash
god doctor
god self-test
cd ~/code/your-project
god task "Add pagination to the invoice list and cover empty pages"
god review "Review the current staged and unstaged invoice changes"
god apply RUN_ID
```

The first task or review installs the kit in private mode if needed. For a shared team install, use `god init .` explicitly. The coding run saves a binary-safe patch and a report under `~/.local/state/god-kit/RUN_ID`. Apply the task patch before asking to review the resulting working-tree diff. A read-only review can also inspect existing tracked code. Patch application checks the current files and fails on conflicting edits. No push or commit is automatic.

The default task asks the Oracle model whether two independent units can own disjoint files. A malformed or overlapping plan uses one developer. Each unit gets its own checkout. A final integrator sees their combined edits and is instructed to run the project's tests. `--single` skips planning for small jobs. `--parallel` also asks two read-only workers to research and design concurrently. On the free VM, model requests can queue behind each other while WSL tools run concurrently.

## Oracle setup

An initialized shared repository also carries its own launcher. From that project, `bash .claude/god/run.sh task "your assignment"` uses the installed worker and the existing WSL tunnel. Run `god status` to locate recent reports and patches.

1. Run `god oracle auth` in WSL. Enter your tenancy OCID, user OCID and home region at the OCI CLI prompts. Upload the generated **public PEM** under your OCI user's API keys. If you already have a DEFAULT API-key profile, keep it. This profile expects key material under `~/.oci`. Do not paste private keys in chat.
2. Run `god oracle up`. This looks up your current public IPv4 address using checkip.amazonaws.com and permits SSH from its /32. Pass `god oracle up ADDRESS/32 COMPARTMENT_OCID` to supply it yourself. The default compartment is the tenancy root. Review the Terraform plan and type `apply` to provision. Check your remaining A1, storage and networking allowance first. On capacity errors, re-run later or select another availability domain with `GOD_AD_INDEX=1 god oracle up` before the first successful launch.
3. Provisioning installs a pinned llama.cpp build and quantized model on the VM and opens the WSL tunnel. Initial compilation and model download can take time. Run `god doctor` for readiness. After a WSL restart, task startup attempts to reconnect the tunnel automatically.

## Troubleshooting

| Symptom | Action |
|---|---|
| CLI or Docker missing | `god doctor` prints what it found. Run `god self-test` to exercise Docker, Codex and the sanitizer with a synthetic model. It builds the default worker image on first use. |
| OCI authentication fails | Check that the public PEM fingerprint, user OCID, tenancy OCID and DEFAULT profile region match. Retry `god oracle up` after uploading the public key. |
| Provisioning or deployment interrupted | Repeat `god oracle up` to reuse Terraform state. After the IP is recorded, `god oracle deploy` retries installation on that VM. Preserve `~/.local/state/god-oracle`, including its state and SSH key. |
| SSH fails after changing internet connections | Run `god oracle up` again to update your allowed source address. |
| Gateway reachable, model loading or failed | Run `god oracle logs` for both systemd units. After the model is ready, retry the task. |
| Tests need a different language or dependencies | Build an image FROM god-kit-worker:0.170.0 with the project's toolchain and dependencies baked in. Set GOD_WORKER_IMAGE to its local tag. Worker runtime has no internet or host package caches. |
| Missing project files | The snapshot includes current contents of Git-tracked regular files and local kit Markdown. Stage new files that the agent should see. Symlinks and excluded paths are skipped. Review the generated patch and test results before applying. |
| Request blocked | Keep attachments, encoded blobs and private keys out of the task. Add project-specific literals or paths to the local exclusions below. |

## Privacy and inference cost

Every worker runs inside a WSL Docker container with no external network, host credentials or Docker socket. It accesses inference through a Unix socket to the WSL sanitizer. Reviews mount the checkout read-only. The Codex CLI uses the Oracle Responses endpoint for both coding and review. An Oracle-only reviewer shares the coding model; it provides a fresh context.

Add one literal identifier per line to `~/.config/god-kit/redact` and one repo-relative glob per line to `~/.config/god-kit/exclude`. The sanitizer also handles known credential patterns and email addresses on prompts and tool outputs. Free-form confidential facts, unfamiliar credential formats and business logic can survive pattern redaction. Local reports may contain project information.

The Oracle worker profile sends every inference request to the model on the VM. Cloud provisioning checks the active subscription and home region before planning. It stops if it cannot confirm the free subscription. Capacity and free allowances are controlled by Oracle.
