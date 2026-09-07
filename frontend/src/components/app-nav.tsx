"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { PreferenceControls, usePreferences } from "./app-preferences";

export function AppNav() {
  const { t } = usePreferences();
  const pathname = usePathname();
  const items = [
    ["/chat", "💬", t.chats],
    ["/sources", "📄", t.sources],
    ["/glossaries", "📚", t.glossaries],
    ["/diagnostics", "📊", t.diagnostics],
    ["/manage", "⚙️", t.settings],
  ];
  return (
    <>
      <nav aria-label={t.navigation}>
        {items.map(([href, icon, label]) => (
          <Link
            className={pathname === href ? "active" : undefined}
            aria-current={pathname === href ? "page" : undefined}
            href={href}
            key={href}
          >
            <span aria-hidden="true">{icon}</span>
            {label}
          </Link>
        ))}
      </nav>
      <PreferenceControls />
    </>
  );
}
