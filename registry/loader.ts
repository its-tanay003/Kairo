/**
 * TypeScript ToolSpec loader for YAML tool definitions.
 */
import fs from "fs";
import path from "path";

export interface ToolParameterSchema {
  type: string;
  properties?: Record<string, any>;
  required?: string[];
  [key: string]: any;
}

export interface ToolSpec {
  id: string;
  name: string;
  version: string;
  description: string;
  category?: string;
  parameters?: ToolParameterSchema;
  timeout_ms?: number;
  metadata?: Record<string, any>;
}

export class ToolRegistry {
  private directory: string;
  private tools: Map<string, ToolSpec> = new Map();

  constructor(dirPath?: string) {
    this.directory = dirPath || path.resolve(__dirname, "tools");
    this.reload();
  }

  public reload(): void {
    this.tools.clear();
    if (!fs.existsSync(this.directory)) {
      return;
    }

    const files = fs.readdirSync(this.directory);
    for (const file of files) {
      if (file.endsWith(".yaml") || file.endsWith(".yml")) {
        try {
          const content = fs.readFileSync(path.join(this.directory, file), "utf-8");
          // Simple key-value parser or standard YAML parser
          const spec = this.parseSimpleYaml(content);
          if (spec.id && spec.name && spec.version) {
            this.tools.set(spec.id, spec as ToolSpec);
          }
        } catch (err) {
          console.error(`[ToolRegistry] Failed parsing ${file}:`, err);
        }
      }
    }
  }

  public get(id: string): ToolSpec | undefined {
    return this.tools.get(id);
  }

  public list(): ToolSpec[] {
    return Array.from(this.tools.values());
  }

  private parseSimpleYaml(yamlStr: string): Partial<ToolSpec> {
    const lines = yamlStr.split("\n");
    const result: any = { parameters: { properties: {} }, metadata: {} };
    let currentKey = "";

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;

      const colonIdx = line.indexOf(":");
      if (colonIdx > 0 && !rawLine.startsWith("  ")) {
        const key = line.slice(0, colonIdx).trim();
        let value = line.slice(colonIdx + 1).trim();
        if (value.startsWith('"') && value.endsWith('"')) {
          value = value.slice(1, -1);
        }
        if (value) {
          result[key] = value;
        }
        currentKey = key;
      }
    }
    return result;
  }
}
