import "./globals.css";
import { AuthGate } from "@/components/auth/auth-gate";
import { ToastProvider } from "@/components/ui/toast-provider";

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <ToastProvider>
          <AuthGate>
            <main className="min-h-screen">{children}</main>
          </AuthGate>
        </ToastProvider>
      </body>
    </html>
  );
}
