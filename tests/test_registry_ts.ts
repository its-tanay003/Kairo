import { ToolRegistry, ToolSpecValidationError } from "./registry/loader";
import fs from "fs";
import path from "path";
import os from "os";

function runTests() {
  console.log("[TS Registry Test] Testing production tools load...");
  const registry = new ToolRegistry(path.resolve(__dirname, "registry", "tools"));
  const tools = registry.list();
  console.log(`  Loaded ${tools.length} tools: ${tools.map(t => t.id).join(", ")}`);
  if (tools.length < 4) {
    throw new Error("Expected at least 4 tools");
  }

  console.log("[TS Registry Test] Testing load-time rejection of malformed spec...");
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "kairo-ts-test-"));
  const badFile = path.join(tmpDir, "incomplete.yaml");
  fs.writeFileSync(badFile, "id: incomplete.tool\nbinary: python\n");

  try {
    new ToolRegistry(tmpDir);
    throw new Error("FAIL: Loader did not reject malformed spec!");
  } catch (err: any) {
    if (err instanceof ToolSpecValidationError) {
      console.log("  ✓ Correctly rejected malformed spec at load time:");
      console.log(`    Errors detected: ${err.errors.length} missing fields`);
    } else {
      throw err;
    }
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }

  console.log("All TypeScript registry tests passed successfully!");
}

runTests();
