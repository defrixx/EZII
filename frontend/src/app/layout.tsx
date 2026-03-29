import "./globals.css";
import { headers } from "next/headers";
import { AuthGate } from "@/components/auth/auth-gate";
import { ToastProvider } from "@/components/ui/toast-provider";

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const nonce = (await headers()).get("x-nonce") || "";

  return (
    <html lang="en-US">
      <head>
        <meta name="csp-nonce" content={nonce} />
      </head>
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
