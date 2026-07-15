import Link from "next/link";
import { listDocs } from "@/lib/docs";

export default function Home() {
  const docs = listDocs();
  return (
    <main className="doc">
      <h1>Documentation</h1>
      {docs.length === 0 ? (
        <p>
          No docs found. Add Markdown files under <code>../docs</code>.
        </p>
      ) : (
        <ul>
          {docs.map((d) => (
            <li key={d.slug.join("/")}>
              <Link href={`/${d.slug.join("/")}`}>{d.title}</Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
