# Agent clients

Open the checkout as a local workspace. The same project-level Skill is under .agents/skills/ai-video-deployer. If discovery is disabled, point the agent to this SKILL.md explicitly.

- In [Codex](https://learn.chatgpt.com/docs/build-skills), select the local checkout and invoke $ai-video-deployer.
- In [WorkBuddy](https://developer.cloud.tencent.com/techpedia/2610/20530), open the local folder. The client documents project discovery under .agents/skills. If needed, use its Skills manager to import the folder. Confirm the execution tool runs on the user's computer.
- In [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md), use a local profile with the filesystem Skill provider and native PowerShell available. The provider can discover .agents/skills at the checkout root. Profile capabilities and prompts vary. [Windows PowerShell provider](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/shell/pwsh-local/README.md)
- In another client, load the standard SKILL.md and use the local console or ask the user to run 打开镜流.cmd. Access to a GitHub URL and access to the user's computer are separate.

Treat a client as verified after checking its exact release, local terminal, approval flow and smoke job.
