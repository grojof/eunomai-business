// Spike for a Node.js connector: answers, inside Claude Cowork, whether a plugin's local server can run on Claude
// Desktop's own Node, trust the organization's certificates, keep secrets with DPAPI, and back a file guard
// through an `mcp_tool` hook. No dependencies: a minimal MCP server over stdio (newline-delimited JSON-RPC).

import { spawnSync } from "node:child_process";
import fs from "node:fs";
import https from "node:https";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";
import tls from "node:tls";

const MARKER = "eunomai-spike-guard";
const dataDir = path.join(process.env.LOCALAPPDATA || os.homedir(), "eunomai-node-spike");
fs.mkdirSync(dataDir, { recursive: true });
const logFile = path.join(dataDir, "spike.log");
const log = (entry) => fs.appendFileSync(logFile, JSON.stringify({ at: new Date().toISOString(), ...entry }) + "\n");

function runtime() {
  return {
    node: process.version,
    electron: process.versions.electron || null,
    exec_path: process.execPath,
    platform: `${process.platform} ${os.release()} ${process.arch}`,
    user: os.userInfo().username,
    plugin_root: process.env.CLAUDE_PLUGIN_ROOT || null,
    data_dir: dataDir,
    system_ca_api: typeof tls.getCACertificates === "function",
    node_options: process.env.NODE_OPTIONS || null,
    path_has_node: (process.env.PATH || "").toLowerCase().includes("node"),
  };
}

function get(url, ca) {
  return new Promise((resolve) => {
    const started = Date.now();
    const request = https.get(url, { ca, timeout: 10000 }, (response) => {
      response.resume();
      resolve({ status: response.statusCode, ms: Date.now() - started });
    });
    request.on("error", (error) => resolve({ error: error.code || error.message, ms: Date.now() - started }));
    request.on("timeout", () => request.destroy(new Error("timeout")));
  });
}

async function reach({ url }) {
  if (!/^https:\/\//.test(url || "")) return { error: "an https URL is needed" };
  const result = { url, bundled_store: await get(url) };
  if (typeof tls.getCACertificates === "function") {
    const ca = [...tls.getCACertificates("default"), ...tls.getCACertificates("system")];
    result.system_store = { certificates: ca.length, ...(await get(url, ca)) };
  } else {
    result.system_store = "tls.getCACertificates is not available in this Node";
  }
  return result;
}

function powershell(script, input) {
  const started = Date.now();
  const run = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", "-"], {
    input: script, env: { ...process.env, SPIKE_INPUT: input }, encoding: "utf8", windowsHide: true, timeout: 20000,
  });
  return { out: (run.stdout || "").trim(), err: (run.stderr || "").trim().slice(0, 300), code: run.status,
           ms: Date.now() - started };
}

function protect() {
  const secret = `spike-${Date.now()}`;
  const encrypt = powershell("Add-Type -AssemblyName System.Security; $b=[Text.Encoding]::UTF8.GetBytes($env:SPIKE_INPUT);" +
    "[Convert]::ToBase64String([Security.Cryptography.ProtectedData]::Protect($b,$null,'CurrentUser'))", secret);
  if (encrypt.code !== 0) return { step: "encrypt", ...encrypt };
  const decrypt = powershell("Add-Type -AssemblyName System.Security; $b=[Convert]::FromBase64String($env:SPIKE_INPUT);" +
    "[Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect($b,$null,'CurrentUser'))",
    encrypt.out);
  return { round_trip_ok: decrypt.out === secret, encrypted_bytes: Buffer.from(encrypt.out, "base64").length,
           encrypt_ms: encrypt.ms, decrypt_ms: decrypt.ms, errors: [encrypt.err, decrypt.err].filter(Boolean),
           language_mode: powershell("$ExecutionContext.SessionState.LanguageMode", "").out };
}

function guard(args) {
  const text = JSON.stringify(args || {});
  const deny = text.includes(MARKER);
  log({ guard: deny ? "deny" : "allow", tool: args?.tool_name || null });
  return deny
    ? { hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "deny",
                              permissionDecisionReason: "eunomai Node spike: guard test marker found." } }
    : {};
}

function guardLog() {
  if (!fs.existsSync(logFile)) return [];
  return fs.readFileSync(logFile, "utf8").trim().split("\n").slice(-20).map((line) => JSON.parse(line));
}

const TOOLS = {
  spike_runtime: { description: "Which Node runs this server (Claude Desktop's own, or one installed), and where.",
                   schema: {}, run: runtime },
  spike_reach: { description: "Request an https URL with Node's bundled certificates and with the system's.",
                 schema: { url: { type: "string" } }, run: reach },
  spike_protect: { description: "Encrypt and decrypt a test secret with Windows DPAPI through PowerShell.",
                   schema: {}, run: protect },
  spike_guard: { description: "Called by the plugin's PreToolUse hook; denies tool calls that mention the test marker.",
                 schema: { tool_name: { type: "string" }, file_path: { type: "string" }, command: { type: "string" } },
                 run: guard },
  spike_guard_log: { description: "The last decisions the guard made.", schema: {}, run: guardLog },
};

function reply(id, result, error) {
  process.stdout.write(JSON.stringify(error ? { jsonrpc: "2.0", id, error } : { jsonrpc: "2.0", id, result }) + "\n");
}

readline.createInterface({ input: process.stdin }).on("line", async (line) => {
  let message;
  try { message = JSON.parse(line); } catch { return; }
  const { id, method, params } = message;
  if (id === undefined) return; // notifications
  if (method === "initialize") {
    log({ start: runtime() });
    return reply(id, { protocolVersion: params?.protocolVersion || "2025-06-18", capabilities: { tools: {} },
                       serverInfo: { name: "eunomai-node-spike", version: "0.0.1" } });
  }
  if (method === "ping") return reply(id, {});
  if (method === "tools/list") {
    return reply(id, { tools: Object.entries(TOOLS).map(([name, t]) => ({
      name, description: t.description, inputSchema: { type: "object", properties: t.schema } })) });
  }
  if (method === "tools/call") {
    const tool = TOOLS[params?.name];
    if (!tool) return reply(id, { content: [{ type: "text", text: "unknown tool" }], isError: true });
    try {
      const result = await tool.run(params.arguments || {});
      return reply(id, { content: [{ type: "text", text: JSON.stringify(result) }] });
    } catch (error) {
      return reply(id, { content: [{ type: "text", text: String(error) }], isError: true });
    }
  }
  reply(id, undefined, { code: -32601, message: `method not found: ${method}` });
});
