"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "..");
const PACKAGE_NAME = "luciazero";
const PACKAGE_VERSION = require(path.join(ROOT, "package.json")).version;

function readText(file) {
  try {
    return fs.readFileSync(file, "utf8");
  } catch (error) {
    if (error && error.code === "ENOENT") return "";
    throw error;
  }
}

function readVersion(directory) {
  const value = readText(path.join(directory, ".luciazero-version")).split(/\r?\n/, 1)[0].trim();
  return value || null;
}

function versionMetadata(directory) {
  const file = path.join(directory, ".luciazero-version");
  return { installedVersion: readVersion(directory), versionFilePresent: fs.existsSync(file) };
}

function detectInstallations(options = {}) {
  const env = options.env || process.env;
  const home = options.home || os.homedir();
  const claudeDir = options.claudeDir || env.CLAUDE_CONFIG_DIR || path.join(home, ".claude");
  const codexDir = options.codexDir || env.CODEX_HOME || path.join(home, ".codex");
  const installations = [];

  const claudeSettings = readText(path.join(claudeDir, "settings.json"));
  const claudeInstalled =
    fs.existsSync(path.join(claudeDir, ".luciazero-version")) ||
    fs.existsSync(path.join(claudeDir, "luciazero.md")) ||
    fs.existsSync(path.join(claudeDir, ".luciazero-managed"));
  if (claudeInstalled) {
    installations.push({
      channel: "claude-classic",
      configDir: claudeDir,
      ...versionMetadata(claudeDir),
      hooks:
        fs.existsSync(path.join(claudeDir, "hooks", "luciazero-verify.sh")) ||
        claudeSettings.includes("hooks/luciazero-verify.sh"),
    });
  }

  const codexAgents = readText(path.join(codexDir, "AGENTS.md"));
  const codexInstalled =
    fs.existsSync(path.join(codexDir, ".luciazero-version")) ||
    fs.existsSync(path.join(codexDir, ".luciazero-managed")) ||
    codexAgents.includes("<!-- luciazero:start -->");
  if (codexInstalled) {
    installations.push({
      channel: "codex",
      configDir: codexDir,
      ...versionMetadata(codexDir),
      hooks: false,
    });
  }

  return installations;
}

function parseSemver(value) {
  const match = String(value || "").match(
    /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/
  );
  if (!match) return null;
  return {
    core: match.slice(1, 4).map(Number),
    prerelease: match[4] ? match[4].split(".") : [],
  };
}

function comparePrerelease(left, right) {
  if (left.length === 0 && right.length === 0) return 0;
  if (left.length === 0) return 1;
  if (right.length === 0) return -1;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    if (left[index] === undefined) return -1;
    if (right[index] === undefined) return 1;
    if (left[index] === right[index]) continue;
    const leftNumber = /^\d+$/.test(left[index]);
    const rightNumber = /^\d+$/.test(right[index]);
    if (leftNumber && rightNumber) return Number(left[index]) < Number(right[index]) ? -1 : 1;
    if (leftNumber !== rightNumber) return leftNumber ? -1 : 1;
    return left[index] < right[index] ? -1 : 1;
  }
  return 0;
}

function compareSemver(leftValue, rightValue) {
  const left = parseSemver(leftValue);
  const right = parseSemver(rightValue);
  if (!left || !right) return null;
  for (let index = 0; index < left.core.length; index += 1) {
    if (left.core[index] !== right.core[index]) {
      return left.core[index] < right.core[index] ? -1 : 1;
    }
  }
  return comparePrerelease(left.prerelease, right.prerelease);
}

function installationStatus(installation, latestVersion) {
  const comparison = compareSemver(installation.installedVersion, latestVersion);
  let status = "unknown";
  if (comparison === 0) status = "current";
  else if (comparison === -1) status = "update-available";
  else if (comparison === 1) status = "ahead";
  return { ...installation, status };
}

function buildCheckResult(installations, latestVersion) {
  const checked = installations.map((installation) => installationStatus(installation, latestVersion));
  return {
    package: PACKAGE_NAME,
    bundledVersion: PACKAGE_VERSION,
    latestVersion,
    cliUpdateAvailable: compareSemver(PACKAGE_VERSION, latestVersion) === -1,
    updateAvailable:
      compareSemver(PACKAGE_VERSION, latestVersion) === -1 ||
      checked.some((installation) => installation.status === "update-available"),
    installations: checked,
  };
}

async function fetchLatestVersion(options = {}) {
  const registry = options.registry || process.env.npm_config_registry || "https://registry.npmjs.org/";
  const request = options.fetch || globalThis.fetch;
  if (typeof request !== "function") throw new Error("this Node.js runtime has no fetch support");
  const base = registry.endsWith("/") ? registry : `${registry}/`;
  const endpoint = new URL(`${PACKAGE_NAME}/latest`, base);
  if (!["http:", "https:"].includes(endpoint.protocol)) {
    throw new Error("npm registry must use http or https");
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs || 5000);
  try {
    const response = await request(endpoint, {
      headers: { Accept: "application/json", "User-Agent": `luciazero/${PACKAGE_VERSION}` },
      redirect: "follow",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`registry returned HTTP ${response.status}`);
    const payload = await response.json();
    if (!payload || !parseSemver(payload.version)) throw new Error("registry returned an invalid version");
    return payload.version;
  } catch (error) {
    if (error && error.name === "AbortError") throw new Error("registry request timed out");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function channelLabel(installation) {
  if (installation.channel === "codex") return "Codex";
  return installation.hooks ? "Claude classic + hooks" : "Claude classic";
}

function writeLine(stream, line = "") {
  stream.write(`${line}\n`);
}

function printSeparateChannelHelp(stream) {
  writeLine(stream, "Claude plugin: claude plugin update luciazero@luciazero, then /reload-plugins");
  writeLine(stream, "Skills only:  npx skills update   (updates all skills in the selected scope; review the prompt)");
}

function checkHelp(stream) {
  writeLine(stream, "Usage: npx luciazero@latest check-update [--json]");
  writeLine(stream, "Checks the npm registry only when this command is run; it never changes files.");
}

async function runCheck(args = [], dependencies = {}) {
  const stdout = dependencies.stdout || process.stdout;
  const stderr = dependencies.stderr || process.stderr;
  if (args.includes("--help") || args.includes("-h")) {
    checkHelp(stdout);
    return 0;
  }
  const unknown = args.filter((arg) => arg !== "--json");
  if (unknown.length > 0) {
    writeLine(stderr, `luciazero check-update: unknown option '${unknown[0]}'`);
    checkHelp(stderr);
    return 64;
  }

  const findInstallations = dependencies.detectInstallations || detectInstallations;
  const getLatestVersion = dependencies.fetchLatestVersion || fetchLatestVersion;
  let latestVersion;
  try {
    latestVersion = await getLatestVersion();
  } catch (error) {
    writeLine(stderr, `luciazero check-update: ${error.message}`);
    writeLine(stderr, "No files were changed. Retry later or check https://www.npmjs.com/package/luciazero.");
    return 1;
  }

  const result = buildCheckResult(findInstallations(), latestVersion);
  if (args.includes("--json")) {
    writeLine(stdout, JSON.stringify(result, null, 2));
    return 0;
  }

  writeLine(stdout, "Luciazero update check");
  writeLine(stdout, `  latest npm release   ${result.latestVersion}`);
  writeLine(stdout, `  this command carries ${result.bundledVersion}`);
  if (result.installations.length === 0) {
    writeLine(stdout, "  no classic Claude/Codex installation detected");
  } else {
    for (const installation of result.installations) {
      const installed = installation.installedVersion || "unknown version";
      const suffix = {
        current: "current",
        "update-available": `update available -> ${result.latestVersion}`,
        ahead: "ahead of the latest public release",
        unknown: `cannot compare -> ${result.latestVersion}`,
      }[installation.status];
      writeLine(stdout, `  ${channelLabel(installation)}: ${installed} (${suffix})`);
    }
  }
  const malformed = result.installations.filter(
    (item) => item.versionFilePresent && item.status === "unknown"
  );
  const updatable = result.installations.filter(
    (item) => item.status === "update-available" || (!item.versionFilePresent && item.status === "unknown")
  );
  if (malformed.length > 0) {
    writeLine(stdout);
    writeLine(stdout, "Cannot update installs with a malformed .luciazero-version file.");
    writeLine(stdout, "Repair it, or remove it only after confirming the installed version.");
  }
  if (updatable.length > 0) {
    writeLine(stdout);
    writeLine(stdout, "Update detected classic/Codex installs with:");
    writeLine(stdout, "  npx luciazero@latest update");
  } else if (result.cliUpdateAvailable) {
    writeLine(stdout);
    writeLine(stdout, "This command is older than the latest release. Re-run it with:");
    writeLine(stdout, "  npx luciazero@latest check-update");
  }
  writeLine(stdout);
  printSeparateChannelHelp(stdout);
  return 0;
}

function updateHelp(stream) {
  writeLine(stream, "Usage: npx luciazero@latest update");
  writeLine(stream, "Updates every detected classic Claude/Codex install and preserves Claude hook mode.");
}

function runInstaller(installation, dependencies = {}) {
  const spawn = dependencies.spawnSync || spawnSync;
  const script = installation.channel === "codex" ? "install-codex.sh" : "install.sh";
  const args = [path.join(ROOT, script)];
  if (installation.channel === "claude-classic" && installation.hooks) args.push("--with-hooks");
  return spawn("bash", args, { env: process.env, stdio: "inherit" });
}

function runUpdate(args = [], dependencies = {}) {
  const stdout = dependencies.stdout || process.stdout;
  const stderr = dependencies.stderr || process.stderr;
  if (args.includes("--help") || args.includes("-h")) {
    updateHelp(stdout);
    return 0;
  }
  if (args.length > 0) {
    writeLine(stderr, `luciazero update: unknown option '${args[0]}'`);
    updateHelp(stderr);
    return 64;
  }

  const findInstallations = dependencies.detectInstallations || detectInstallations;
  const installations = findInstallations();
  if (installations.length === 0) {
    writeLine(stderr, "No classic Claude/Codex installation detected; nothing changed.");
    printSeparateChannelHelp(stderr);
    return 1;
  }
  const newerInstallations = installations.filter(
    (installation) => compareSemver(installation.installedVersion, PACKAGE_VERSION) === 1
  );
  if (newerInstallations.length > 0) {
    for (const installation of newerInstallations) {
      writeLine(
        stderr,
        `Refusing to downgrade ${channelLabel(installation)} from ` +
          `${installation.installedVersion} to bundled ${PACKAGE_VERSION}.`
      );
    }
    writeLine(stderr, "Run npx luciazero@latest update so the updater itself is current.");
    return 1;
  }
  const invalidMetadata = installations.filter(
    (installation) => installation.versionFilePresent && !parseSemver(installation.installedVersion)
  );
  if (invalidMetadata.length > 0) {
    for (const installation of invalidMetadata) {
      writeLine(
        stderr,
        `Refusing to update ${channelLabel(installation)}: .luciazero-version is malformed.`
      );
    }
    writeLine(stderr, "Repair or remove the malformed sidecar after confirming the installed version, then retry.");
    return 1;
  }
  if (process.platform === "win32") {
    writeLine(stderr, "Luciazero installers need Bash. Run this command inside WSL.");
    return 1;
  }

  writeLine(stdout, `Updating detected installations with Luciazero ${PACKAGE_VERSION}:`);
  let failed = false;
  for (const installation of installations) {
    writeLine(stdout, `\n-- ${channelLabel(installation)} (${installation.configDir})`);
    const result = runInstaller(installation, dependencies);
    if (result.error || result.status !== 0) {
      failed = true;
      const detail = result.error ? `: ${result.error.message}` : ` (exit ${result.status})`;
      writeLine(stderr, `luciazero update: ${channelLabel(installation)} failed${detail}`);
    }
  }
  if (failed) return 1;

  writeLine(stdout, "\nUpdated all detected classic/Codex installations.");
  writeLine(stdout, "Start a new agent session so the refreshed doctrine and skills are loaded.");
  return 0;
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  let status;
  if (command === "check") status = await runCheck(args);
  else if (command === "update") status = runUpdate(args);
  else {
    writeLine(process.stderr, `luciazero update helper: unknown command '${command || ""}'`);
    status = 64;
  }
  process.exitCode = status;
}

if (require.main === module) {
  main().catch((error) => {
    writeLine(process.stderr, `luciazero update helper: ${error.message}`);
    process.exitCode = 1;
  });
}

module.exports = {
  buildCheckResult,
  compareSemver,
  detectInstallations,
  fetchLatestVersion,
  runCheck,
  runUpdate,
};
