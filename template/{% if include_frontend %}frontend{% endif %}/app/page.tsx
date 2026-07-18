import site from "./site.json";

export default function Home() {
  return (
    <main className="landing">
      <h1>{site.name}</h1>
      <p>
        Frontend scaffolded from the <code>zynth-setup</code> template. Edit{" "}
        <code>app/page.tsx</code> to get started — the backend health check is
        at <a href="/health">/health</a>.
      </p>
    </main>
  );
}
