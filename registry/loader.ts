/**
 * TypeScript ToolSpec loader for YAML tool definitions.
 * Enforces the exact 16-field ToolSpec blueprint schema on startup:
 * (id, binary, category, capabilities, inputs, outputs, side_effects,
 * privilege, gui, parser, prerequisites, docs, success_signals,
 * failure_signals, rollback, version_compatibility).
 *
 * Malformed specs are rejected at load time, not at execution time.
 */

import fs from "fs";
import path from "path";

// Attempt loading standard yaml parser
let parseYaml: (text: string) => any;
try {
  const yamlPkg = require("yaml");
  parseYaml = yamlPkg.parse;
} catch {
  parseYaml = (text: string) => {
    throw new Error("YAML parser package not found. Please run 'npm install yaml'.");
  };
}

export class ToolSpecValidationError extends Error {
  public filePath?: string;
  public errors: string[];

  constructor(message: string, filePath?: string, errors: string[] = []) {
    super(message);
    this.name = "ToolSpecValidationError";
    this.filePath = filePath;
    this.errors = errors;
  }
}

export interface ToolSpec {
  // 16 Core Blueprint Fields
  id: string;
  binary: string;
  category: string;
  capabilities: string[];
  inputs: Record<string, any>;
  outputs: Record<string, any>;
  side_effects: string[];
  privilege: "user" | "root" | "admin" | "elevated" | "kernel" | "guest" | string;
  gui: boolean | Record<string, any>;
  parser: string | Record<string, any>;
  prerequisites: string[];
  docs: string | Record<string, any>;
  success_signals: Record<string, any>;
  failure_signals: Record<string, any>;
  rollback: string | Record<string, any>;
  version_compatibility: string | Record<string, any>;

  // Convenience / Backward-Compatibility Fields
  name?: string;
  version?: string;
  description?: string;
  timeout_ms?: number;
  parameters?: Record<string, any>;
  metadata?: Record<string, any>;
}

export const REQUIRED_TOOLSPEC_FIELDS: (keyof ToolSpec)[] = [
  "id",
  "binary",
  "category",
  "capabilities",
  "inputs",
  "outputs",
  "side_effects",
  "privilege",
  "gui",
  "parser",
  "prerequisites",
  "docs",
  "success_signals",
  "failure_signals",
  "rollback",
  "version_compatibility",
];

export class ToolRegistry {
  private directory: string;
  private schemaPath: string;
  private strict: boolean;
  private tools: Map<string, ToolSpec> = new Map();

  constructor(dirPath?: string, schemaPath?: string, strict: boolean = true) {
    this.directory = dirPath || path.resolve(__dirname, "tools");
    this.schemaPath = schemaPath || path.resolve(__dirname, "schema", "toolspec.schema.json");
    this.strict = strict;
    this.reload();
  }

  public validateSpec(data: any): string[] {
    const errors: string[] = [];
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return ["ToolSpec root must be a key-value mapping object."];
    }

    for (const field of REQUIRED_TOOLSPEC_FIELDS) {
      if (data[field] === undefined || data[field] === null) {
        errors.push(`Missing required field: '${field}'`);
      }
    }

    if (data.id && typeof data.id !== "string") {
      errors.push("'id' must be a string");
    }
    if (data.binary && typeof data.binary !== "string") {
      errors.push("'binary' must be a string");
    }
    if (data.category && typeof data.category !== "string") {
      errors.push("'category' must be a string");
    }
    if (data.capabilities && !Array.isArray(data.capabilities)) {
      errors.push("'capabilities' must be an array of strings");
    }
    if (data.inputs && (typeof data.inputs !== "object" || Array.isArray(data.inputs))) {
      errors.push("'inputs' must be an object");
    }
    if (data.outputs && (typeof data.outputs !== "object" || Array.isArray(data.outputs))) {
      errors.push("'outputs' must be an object");
    }
    if (data.side_effects && !Array.isArray(data.side_effects)) {
      errors.push("'side_effects' must be an array of strings");
    }
    if (data.prerequisites && !Array.isArray(data.prerequisites)) {
      errors.push("'prerequisites' must be an array of strings");
    }
    if (data.success_signals && (typeof data.success_signals !== "object" || Array.isArray(data.success_signals))) {
      errors.push("'success_signals' must be an object");
    }
    if (data.failure_signals && (typeof data.failure_signals !== "object" || Array.isArray(data.failure_signals))) {
      errors.push("'failure_signals' must be an object");
    }

    return errors;
  }

  public reload(): void {
    this.tools.clear();
    if (!fs.existsSync(this.directory)) {
      return;
    }

    const files = fs.readdirSync(this.directory);
    for (const file of files) {
      if (file.endsWith(".yaml") || file.endsWith(".yml")) {
        const fullPath = path.join(this.directory, file);
        let parsed: any;

        try {
          const content = fs.readFileSync(fullPath, "utf-8");
          parsed = parseYaml(content);
        } catch (err: any) {
          const msg = `Failed to parse YAML file '${file}': ${err.message}`;
          console.error(`[ToolRegistry] ${msg}`);
          if (this.strict) {
            throw new ToolSpecValidationError(msg, fullPath);
          }
          continue;
        }

        const errors = this.validateSpec(parsed);
        if (errors.length > 0) {
          const msg = `ToolSpec schema validation rejected '${file}' at load time: ${errors.join("; ")}`;
          console.error(`[ToolRegistry] ${msg}`);
          if (this.strict) {
            throw new ToolSpecValidationError(msg, fullPath, errors);
          }
          continue;
        }

        const spec: ToolSpec = {
          id: String(parsed.id),
          binary: String(parsed.binary),
          category: String(parsed.category),
          capabilities: parsed.capabilities || [],
          inputs: parsed.inputs || {},
          outputs: parsed.outputs || {},
          side_effects: parsed.side_effects || [],
          privilege: parsed.privilege || "user",
          gui: parsed.gui !== undefined ? parsed.gui : false,
          parser: parsed.parser || "raw",
          prerequisites: parsed.prerequisites || [],
          docs: parsed.docs || {},
          success_signals: parsed.success_signals || {},
          failure_signals: parsed.failure_signals || {},
          rollback: parsed.rollback || {},
          version_compatibility: parsed.version_compatibility || {},
          name: parsed.name || parsed.id,
          version: String(parsed.version || "1.0.0"),
          description: parsed.description || "",
          timeout_ms: Number(parsed.timeout_ms || 5000),
          parameters: parsed.parameters || parsed.inputs || {},
          metadata: parsed.metadata || {},
        };

        this.tools.set(spec.id, spec);
      }
    }
  }

  public get(id: string): ToolSpec | undefined {
    return this.tools.get(id);
  }

  public list(): ToolSpec[] {
    return Array.from(this.tools.values());
  }

  public has(id: string): boolean {
    return this.tools.has(id);
  }

  public count(): number {
    return this.tools.size;
  }
}
