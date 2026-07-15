import fs from "node:fs";
import path from "node:path";

const DOCS_DIR = path.join(process.cwd(), "..", "docs");

export type DocMeta = { slug: string[]; title: string };

export function listDocs(): DocMeta[] {
  const out: DocMeta[] = [];
  const walk = (dir: string, prefix: string[]): void => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        walk(path.join(dir, entry.name), [...prefix, entry.name]);
      } else if (entry.name.endsWith(".md")) {
        const slug = [...prefix, entry.name.replace(/\.md$/, "")];
        out.push({ slug, title: slug.join(" / ") });
      }
    }
  };
  walk(DOCS_DIR, []);
  return out.sort((a, b) => a.slug.join("/").localeCompare(b.slug.join("/")));
}

export function readDoc(slug: string[]): string | null {
  const file = path.join(DOCS_DIR, ...slug) + ".md";
  if (!fs.existsSync(file)) return null;
  return fs.readFileSync(file, "utf8");
}
