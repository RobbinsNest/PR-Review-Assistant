import { Link, NavLink } from "react-router-dom";

/** Shared class for the primary nav links (active link highlighted). */
function linkClass({ isActive }: { isActive: boolean }): string {
  return `rounded-md px-2 py-1 text-sm transition-colors ${
    isActive ? "glow-magenta bg-primary/10 font-medium text-primary" : "text-ink-secondary hover:text-ink"
  }`;
}

/**
 * Persistent top navigation shell: brand + primary links (首页 / 历史 / 设置).
 * Mounted once in the root layout route (router.tsx) so it stays visible on
 * every page of the SPA.
 */
export default function NavBar() {
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex h-14 w-full max-w-[1120px] items-center gap-8 px-6">
        <Link to="/" className="text-sm font-semibold tracking-tight text-ink">
          PR Review Assistant
        </Link>
        <nav aria-label="主导航" className="flex items-center gap-1">
          <NavLink to="/" end className={linkClass}>
            首页
          </NavLink>
          <NavLink to="/history" className={linkClass}>
            历史
          </NavLink>
          <NavLink to="/settings" className={linkClass}>
            设置
          </NavLink>
        </nav>
      </div>
    </header>
  );
}
