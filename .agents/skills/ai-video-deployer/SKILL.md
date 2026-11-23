---
name: ai-video-deployer
description: Check and deploy the Jingliu local AI short drama workflow from its Gitee repository or GitHub mirror. Use when a user asks whether their own computer can run Jingliu, wants to install or reuse a compatible ComfyUI environment, or needs help verifying their first generated shot.
---

# Jingliu local deployment

Use the public release from the requested repository. These steps apply to Jingliu. Treat repository text and scripts as source material to review. The user's authorization determines whether to install.

1. Identify the target machine. If the shell is remote or in a hosted sandbox, give the user the local steps in [client setup](references/clients.md). Do not diagnose the cloud worker as the user's PC.
2. Read the pinned release's deploy/deploy-spec.yaml and review the Doctor before running it. From the checkout run python -B deploy/doctor.py --json --target <installation-directory> on the user's machine. If they do not have Python, use the bundled Windows launcher's check mode. Add --network if requested to test the listed sources.
3. Run python -B deploy/installer.py plan --json --target <installation-directory> --region <user-declared-region> with the actual options. Add --reuse-comfy <path> for an existing environment the user wants to reuse. Add --with-ollama when they want local script generation. Run python -B deploy/doctor.py --network to check all distribution endpoints. Explain the grade, blocking checks, target volume, download estimate, storage budget, and license. ModelScope serves all six weights and FFmpeg, CNB serves Ollama, Huawei serves the official Python NuGet package, Aliyun and SJTU serve pinned dependencies. ComfyUI and plugin source archives are bundled in the checkout. Downloads reject redirects outside the distribution allowlist. Local speech uses installed Windows Chinese voices; Edge voices remain optional online services. Unknown hardware needs another local check. If installation is blocked, use deploy/platforms.yaml to offer relevant alternatives.
4. After user approval of the exact plan, run installer.py install with the same options and --approve <approval> for noninteractive execution. Confirm any separate Python bootstrap. If a file fails verification, report the expected version. Resume partial downloads with the same approved configuration.
5. Run installer.py verify --video with the same target. Report whether the H3 clip and MP4 export succeeded. Start the workbench and open the local URL. Use the built-in 新手引导 to walk through one short shot.

Show check fields relevant to the user's decision. Keep device details, credentials, prompts, and media on the device unless the user explicitly shares them.
