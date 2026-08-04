/**
 * HomePage skeleton (T14). The full PR form (URL input, optional GitHub
 * token, example-PR quick start) is implemented in T15.
 */
export default function HomePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-4 px-6">
      <h1 className="text-3xl font-semibold tracking-tight text-ink">
        PR Review Assistant
      </h1>
      <p className="text-sm text-ink-secondary">
        AI 驱动的 GitHub Pull Request 评审助手
      </p>
    </main>
  );
}
