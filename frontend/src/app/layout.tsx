import "./globals.css";
import { AuthGate } from "@/components/auth/auth-gate";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <AuthGate>
          <main className="min-h-screen">{children}</main>
        </AuthGate>
      </body>
    </html>
  );
}
