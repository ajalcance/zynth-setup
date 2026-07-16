import Link from "next/link";
import { notFound } from "next/navigation";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { listDocs, readDoc } from "@/lib/docs";

export function generateStaticParams() {
  return listDocs().map((d) => ({ slug: d.slug }));
}

// Only slugs from generateStaticParams are served; an unknown path 404s instead
// of being rendered on demand (which would let a request slug reach the filesystem).
export const dynamicParams = false;

export default async function DocPage({
  params,
}: {
  params: Promise<{ slug: string[] }>;
}) {
  const { slug } = await params;
  const content = readDoc(slug);
  if (content === null) notFound();
  return (
    <main className="doc">
      <p>
        <Link href="/">← All docs</Link>
      </p>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </main>
  );
}
