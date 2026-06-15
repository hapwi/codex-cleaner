#!/usr/bin/env node

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const readline = require("node:readline");

const repoRoot = path.resolve(__dirname, "..");
const packageJson = JSON.parse(fs.readFileSync(path.join(repoRoot, "package.json"), "utf8"));
const packageVersion = packageJson.version || "0.0.0";
const pythonScript = path.join(repoRoot, "scripts", "codex_cleaner.py");
const skillScript = path.join(repoRoot, "skill.sh");
const skillName = "codex-cleaner";
const agentsHome = process.env.AGENTS_HOME || path.join(os.homedir(), ".agents");
const skillPath = path.join(agentsHome, "skills", skillName);
const skillFile = path.join(skillPath, "SKILL.md");
const bundledSkillFile = path.join(repoRoot, "skills", skillName, "SKILL.md");
const invokedName = path.basename(process.argv[1] || "codex-cleaner");
const invokedAsRunner = process.env.CODEX_CLEANER_RUNNER === "1" || invokedName === "codex-cleaner-run";

function usage() {
  console.log(`Codex Cleaner

Usage:
  codex-cleaner                         Check/install/update the Codex skill
  codex-cleaner --yes                   Install/update the skill without prompting
  codex-cleaner install-skill [--force] Install the bundled $codex-cleaner skill
  codex-cleaner skill-status            Show whether the $codex-cleaner skill is installed
  codex-cleaner version                 Show CLI and bundled skill versions

Codex agents should run cleanup through:
  codex-cleaner-run audit [--json]
`);
}

function runnerUsage() {
  console.log(`Codex Cleaner Runner

Usage:
  codex-cleaner-run audit [--json]          Run a read-only audit

Cleanup commands:
  codex-cleaner-run archive-old-chats --days 10 [--json]
  codex-cleaner-run archive-all-chats [--json]
  codex-cleaner-run prune-stale-projects [--json]
  codex-cleaner-run rotate-logs [--json]
  codex-cleaner-run archive-stale-worktrees --days 7 [--json]

Advanced:
  codex-cleaner-run raw -- <codex_cleaner.py flags>
`);
}

function removeFlag(args, flag) {
  const next = [];
  let present = false;
  for (const arg of args) {
    if (arg === flag) {
      present = true;
    } else {
      next.push(arg);
    }
  }
  return { present, args: next };
}

function takeOption(args, names) {
  const next = [];
  let value = null;
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    const matched = names.find((name) => arg === name || arg.startsWith(`${name}=`));
    if (!matched) {
      next.push(arg);
      continue;
    }
    if (arg.includes("=")) {
      value = arg.slice(arg.indexOf("=") + 1);
    } else if (index + 1 < args.length) {
      value = args[index + 1];
      index += 1;
    }
  }
  return { value, args: next };
}

function installedSkill() {
  return fs.existsSync(skillFile);
}

function readSkillVersion(file) {
  try {
    const content = fs.readFileSync(file, "utf8");
    const match = content.match(/^\s*version:\s*["']?([^"'\n]+)["']?\s*$/m);
    return match ? match[1].trim() : null;
  } catch {
    return null;
  }
}

function versionInfo() {
  return {
    cli: packageVersion,
    bundledSkill: readSkillVersion(bundledSkillFile) || packageVersion,
    installedSkill: readSkillVersion(skillFile),
    installedSkillPath: skillFile,
  };
}

function printVersionFooter() {
  const versions = versionInfo();
  const installed = versions.installedSkill ? `installed skill v${versions.installedSkill}` : "installed skill missing";
  console.log("");
  console.log(`Codex Cleaner version: CLI v${versions.cli} | bundled skill v${versions.bundledSkill} | ${installed}`);
}

function runSkillInstaller(args = []) {
  const result = spawnSync("sh", [skillScript, "install", ...args], {
    cwd: repoRoot,
    stdio: "inherit",
  });
  return result.status ?? 1;
}

function printCodexStartMessage(status) {
  const versions = versionInfo();
  console.log("");
  console.log(`$${skillName} skill ${status} at ${skillPath}`);
  console.log(`installed skill version: ${versions.installedSkill || "unknown"}`);
  console.log("");
  console.log("Next step:");
  console.log("1. Start a new Codex chat so the skill registry reloads.");
  console.log(`2. Invoke $${skillName}.`);
  console.log("");
  console.log("Codex Cleaner will run the audit inside that chat and show the cleanup menu there.");
  printVersionFooter();
}

function printCurrentSkillMessage() {
  const versions = versionInfo();
  console.log(`$${skillName} skill is up to date at ${skillPath}`);
  console.log(`installed skill version: ${versions.installedSkill || "unknown"}`);
  console.log("");
  console.log("Next step:");
  console.log("Start a new Codex chat and invoke $codex-cleaner.");
  console.log("");
  console.log("The installed skill will run the cleaner through codex-cleaner-run inside that chat.");
  printVersionFooter();
}

function runPython(pythonArgs, options = {}) {
  const json = options.json === true;
  if (!fs.existsSync(pythonScript)) {
    const message = `missing cleaner script: ${pythonScript}`;
    if (json) {
      console.log(JSON.stringify({ ok: false, error: message }, null, 2));
      return 1;
    }
    console.error(message);
    return 1;
  }

  if (!json) {
    const result = spawnSync("python3", [pythonScript, ...pythonArgs], {
      cwd: repoRoot,
      stdio: "inherit",
    });
    printVersionFooter();
    return result.status ?? 1;
  }

  const result = spawnSync("python3", [pythonScript, ...pythonArgs], {
    cwd: repoRoot,
    encoding: "utf8",
  });
  console.log(
    JSON.stringify(
      {
        ok: result.status === 0,
        command: ["python3", "scripts/codex_cleaner.py", ...pythonArgs],
        exitCode: result.status ?? 1,
        version: versionInfo(),
        stdout: result.stdout || "",
        stderr: result.stderr || "",
      },
      null,
      2,
    ),
  );
  return result.status ?? 1;
}

function promptYesNo(question) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout,
    });
    rl.question(`${question} [y/N] `, (answer) => {
      rl.close();
      resolve(/^y(es)?$/i.test(answer.trim()));
    });
  });
}

async function bootstrap(args) {
  const force = removeFlag(args, "--force");
  const yes = removeFlag(force.args, "--yes");
  if (installedSkill() && !force.present) {
    const versions = versionInfo();
    if (versions.installedSkill !== versions.bundledSkill) {
      const installed = versions.installedSkill || "unknown";
      const prompt = `Update the $${skillName} skill from v${installed} to v${versions.bundledSkill}?`;
      if (!process.stdin.isTTY && !yes.present) {
        console.error(`$${skillName} skill is installed but stale at ${skillPath}`);
        console.error(`installed=${installed} bundled=${versions.bundledSkill}`);
        console.error("Run `codex-cleaner install-skill --force` or rerun bootstrap with `--yes`.");
        return 2;
      }
      const shouldUpdate = yes.present || (await promptYesNo(prompt));
      if (shouldUpdate) {
        const code = runSkillInstaller(["--force"]);
        if (code !== 0) {
          return code;
        }
        printCodexStartMessage("updated");
        return 0;
      } else {
        console.log("No changes made.");
        printCodexStartMessage("is still installed");
        return 0;
      }
    }
    printCurrentSkillMessage();
    return 0;
  }

  if (!process.stdin.isTTY && !yes.present) {
    console.error(`$${skillName} skill is not installed at ${skillPath}`);
    console.error("Run `codex-cleaner install-skill` or rerun with `--yes`.");
    return 2;
  }

  const shouldInstall = yes.present || (await promptYesNo(`Install the $${skillName} skill into ${skillPath}?`));
  if (!shouldInstall) {
    console.log("No changes made.");
    return 0;
  }

  const code = runSkillInstaller(force.present ? ["--force"] : []);
  if (code !== 0) {
    return code;
  }
  printCodexStartMessage("installed");
  return 0;
}

function mapCommand(command, args) {
  let current = [...args];
  const jsonFlag = removeFlag(current, "--json");
  current = jsonFlag.args;

  switch (command) {
    case "audit":
      return { pythonArgs: current, json: jsonFlag.present };
    case "archive-old-chats": {
      const days = takeOption(current, ["--days", "-d"]);
      current = days.args;
      return {
        pythonArgs: [
          "--apply",
          "--archive-old-chats",
          "--archive-older-than-days",
          days.value || "10",
          ...current,
        ],
        json: jsonFlag.present,
      };
    }
    case "archive-all-chats":
      return { pythonArgs: ["--apply", "--archive-all-chats", ...current], json: jsonFlag.present };
    case "prune-stale-projects":
      return { pythonArgs: ["--apply", "--prune-stale-projects", ...current], json: jsonFlag.present };
    case "rotate-logs": {
      const noWait = removeFlag(current, "--no-wait");
      current = noWait.args;
      const waitArgs = noWait.present ? [] : ["--wait-for-logs-free"];
      return { pythonArgs: ["--apply", "--rotate-logs", ...waitArgs, ...current], json: jsonFlag.present };
    }
    case "archive-stale-worktrees": {
      const days = takeOption(current, ["--days", "-d"]);
      current = days.args;
      return {
        pythonArgs: [
          "--apply",
          "--archive-stale-worktrees",
          "--worktree-older-than-days",
          days.value || "7",
          ...current,
        ],
        json: jsonFlag.present,
      };
    }
    case "raw": {
      const passthrough = current[0] === "--" ? current.slice(1) : current;
      return { pythonArgs: passthrough, json: jsonFlag.present };
    }
    default:
      return null;
  }
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.includes("--help") || argv.includes("-h")) {
    if (invokedAsRunner) {
      runnerUsage();
    } else {
      usage();
    }
    return 0;
  }

  const command = argv[0];
  const rest = command ? argv.slice(1) : [];

  if (invokedAsRunner) {
    const runnerCommand = command || "audit";
    const mapped = mapCommand(runnerCommand, command ? rest : argv);
    if (!mapped) {
      console.error(`Unknown runner command: ${runnerCommand}`);
      runnerUsage();
      return 2;
    }
    return runPython(mapped.pythonArgs, { json: mapped.json });
  }

  if (!command || command.startsWith("-")) {
    return bootstrap(argv);
  }

  if (command === "install-skill") {
    const force = removeFlag(rest, "--force");
    return runSkillInstaller(force.present ? ["--force"] : []);
  }

  if (command === "version") {
    const versions = versionInfo();
    console.log(`codex-cleaner cli v${versions.cli}`);
    console.log(`bundled skill v${versions.bundledSkill}`);
    console.log(`installed skill ${versions.installedSkill ? `v${versions.installedSkill}` : "missing"}`);
    console.log(`installed skill path ${versions.installedSkillPath}`);
    return 0;
  }

  if (command === "skill-status") {
    const versions = versionInfo();
    if (installedSkill()) {
      console.log(`installed ${skillFile}`);
      console.log(`installed skill version: ${versions.installedSkill || "unknown"}`);
      console.log(`bundled skill version: ${versions.bundledSkill}`);
      console.log(`status: ${versions.installedSkill === versions.bundledSkill ? "current" : "stale"}`);
      return 0;
    }
    console.log(`missing ${skillFile}`);
    console.log(`bundled skill version: ${versions.bundledSkill}`);
    return 1;
  }

  console.error(`Unknown command: ${command}`);
  usage();
  return 2;
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
