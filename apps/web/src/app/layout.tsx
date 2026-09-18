import type { Metadata } from "next";

import "./styles.css";
import "./operations.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "ReadySet",
  description: "Secure enterprise onboarding knowledge",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
