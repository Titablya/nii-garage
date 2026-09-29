import type { Metadata } from "next";
import "./globals.css";
import "./light-refresh.css";
import "./motion-integration.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://нии-гараж.рф"),
  alternates: { canonical: "/" },
  title: "Арена переговоров",
  description: "Тренажёр деловых переговоров",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
