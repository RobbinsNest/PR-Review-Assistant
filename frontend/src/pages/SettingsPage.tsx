import { useEffect, useState, type FormEvent } from "react";
import {
  clearSettings,
  getSettings,
  testSettings,
  updateSettings,
  type LLMSettings,
  type SettingsTestResult,
} from "../api/client";

const INPUT_CLASS =
  "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/30";

/**
 * Settings page: shows the masked LLM configuration (base_url / model /
 * api_key_configured / api_key_masked), lets the user update base_url/model/
 * key, clear the key, and run a connectivity probe that reports latency or a
 * redacted error. The backend never returns the plaintext key.
 */
export default function SettingsPage() {
  const [settings, setSettings] = useState<LLMSettings | null>(null);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<SettingsTestResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    getSettings()
      .then((current) => {
        if (cancelled) {
          return;
        }
        setSettings(current);
        setBaseUrl(current.base_url);
        setModel(current.model);
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setError(err instanceof Error ? err.message : "加载设置失败");
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    setTestResult(null);
    try {
      const next = await updateSettings({
        base_url: baseUrl.trim() || undefined,
        model: model.trim() || undefined,
        api_key: apiKey.trim() || undefined,
      });
      setSettings(next);
      setBaseUrl(next.base_url);
      setModel(next.model);
      setApiKey("");
      setNotice("设置已保存");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const handleClearKey = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    setTestResult(null);
    try {
      const next = await clearSettings();
      setSettings(next);
      setApiKey("");
      setNotice("API Key 已清除");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "清除失败");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    setNotice(null);
    setTestResult(null);
    try {
      setTestResult(await testSettings());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "连通性测试失败");
    } finally {
      setTesting(false);
    }
  };

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1120px] space-y-4 px-6 py-10">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">设置</h1>
        <p className="mt-1 text-sm text-ink-secondary">LLM 配置与凭据状态（Key 仅显示掩码）</p>
      </header>

      {loading ? (
        <p className="text-sm text-ink-secondary">加载中…</p>
      ) : (
        <>
          <section className="rounded-lg border border-line bg-surface p-6" aria-label="当前配置">
            <h2 className="text-sm font-medium text-ink">当前配置</h2>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex items-center justify-between gap-4">
                <dt className="text-ink-secondary">base_url</dt>
                <dd className="truncate font-mono text-ink">{settings?.base_url}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-ink-secondary">model</dt>
                <dd className="truncate font-mono text-ink">{settings?.model}</dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-ink-secondary">API Key</dt>
                <dd className="text-ink">
                  {settings?.api_key_configured ? "已配置" : "未配置"}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-4">
                <dt className="text-ink-secondary">掩码</dt>
                <dd className="font-mono text-ink">{settings?.api_key_masked ?? "—"}</dd>
              </div>
            </dl>
          </section>

          <form
            onSubmit={(event) => void handleSave(event)}
            className="space-y-4 rounded-lg border border-line bg-surface p-6"
            aria-label="更新配置"
          >
            <h2 className="text-sm font-medium text-ink">更新配置</h2>

            <label className="block">
              <span className="mb-1 block text-sm font-medium text-ink">base_url</span>
              <input
                type="url"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://api.deepseek.com"
                autoComplete="off"
                spellCheck={false}
                className={INPUT_CLASS}
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-sm font-medium text-ink">model</span>
              <input
                type="text"
                value={model}
                onChange={(event) => setModel(event.target.value)}
                placeholder="deepseek-v4-flash"
                autoComplete="off"
                spellCheck={false}
                className={INPUT_CLASS}
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-sm font-medium text-ink">API Key</span>
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                placeholder={settings?.api_key_configured ? "已配置，留空保持不变" : "sk-..."}
                autoComplete="off"
                className={INPUT_CLASS}
              />
            </label>

            {error && (
              <p
                role="alert"
                className="rounded-md border border-error/30 bg-error/5 px-3 py-2 text-sm text-error"
              >
                {error}
              </p>
            )}
            {notice && (
              <p
                role="status"
                className="rounded-md border border-success/30 bg-success/5 px-3 py-2 text-sm text-success"
              >
                {notice}
              </p>
            )}
            {testResult && (
              <p
                role="status"
                className={`rounded-md border px-3 py-2 text-sm ${
                  testResult.ok
                    ? "border-success/30 bg-success/5 text-success"
                    : "border-error/30 bg-error/5 text-error"
                }`}
              >
                {testResult.ok ? "连通正常" : "连通失败"} · 延迟 {testResult.latency_ms}ms
                {testResult.error ? ` · ${testResult.error}` : ""}
              </p>
            )}

            <div className="flex flex-wrap items-center gap-3 pt-1">
              <button
                type="submit"
                disabled={saving || testing}
                className="rounded-md bg-primary glow-cyan px-4 py-2 text-sm font-medium text-surface transition-colors hover:bg-primary-strong disabled:cursor-not-allowed disabled:opacity-40"
              >
                {saving ? "保存中…" : "保存"}
              </button>
              <button
                type="button"
                onClick={() => void handleTest()}
                disabled={testing || saving}
                className="rounded-md border border-line-strong bg-surface px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-40"
              >
                {testing ? "测试中…" : "测试连通性"}
              </button>
              {settings?.api_key_configured && (
                <button
                  type="button"
                  onClick={() => void handleClearKey()}
                  disabled={saving || testing}
                  className="rounded-md bg-error px-4 py-2 text-sm font-medium text-surface transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  清除 Key
                </button>
              )}
            </div>
          </form>
        </>
      )}
    </main>
  );
}