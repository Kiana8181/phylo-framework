import "./globals.css";
import Providers from "./providers";
import { Roboto_Condensed } from "next/font/google";

export const metadata = {
  title: "Phylo Runner",
  description: "Phylogeny methods runner",
};

const robotoCondensed = Roboto_Condensed({
  subsets: ["latin"],
  variable: "--font-roboto-condensed",
});

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={robotoCondensed.variable}
    >
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
