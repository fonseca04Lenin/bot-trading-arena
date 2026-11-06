import type { Metadata, Viewport } from "next";
import { Caveat, IBM_Plex_Mono, Libre_Caslon_Display, Source_Serif_4, UnifrakturMaguntia } from "next/font/google";
import "./globals.css";
import { Footer } from "@/components/Footer";
import { GlossaryProvider } from "@/components/Glossary";
import { LiveProvider } from "@/components/Live";
import { Masthead } from "@/components/Masthead";
import { getFrontPage, getGlossary, type FrontPage, type GlossaryEntry } from "@/lib/api";

const fraktur = UnifrakturMaguntia({ weight: "400", subsets: ["latin"], variable: "--font-fraktur", display: "swap" });
const caslon = Libre_Caslon_Display({ weight: "400", subsets: ["latin"], variable: "--font-caslon", display: "swap" });
const source = Source_Serif_4({ subsets: ["latin"], variable: "--font-source", display: "swap" });
const hand = Caveat({ weight: ["500", "700"], subsets: ["latin"], variable: "--font-hand", display: "swap" });
const plex = IBM_Plex_Mono({ weight: ["400", "500", "600"], subsets: ["latin"], variable: "--font-plex", display: "swap" });

export const metadata: Metadata = {
  title: { default: "The Arena Daily", template: "%s · The Arena Daily" },
  description: "Seven trading bots compete with paper money in real time. Every trade comes with a reason.",
};
export const viewport: Viewport = { width: "device-width", initialScale: 1 };

const THEME_SCRIPT = `try{var t=localStorage.getItem('arena-theme');if(t)document.documentElement.setAttribute('data-theme',t)}catch(e){}`;

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const [page, glossary] = await Promise.all([
    getFrontPage().catch((): FrontPage | null => null),
    getGlossary().catch((): GlossaryEntry[] => []),
  ]);
  return (
    <html lang="en" className={`${fraktur.variable} ${caslon.variable} ${source.variable} ${plex.variable} ${hand.variable}`} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} /></head>
      <body>
        <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true" focusable="false">
          <defs>
            <filter id="wobble" x="-2%" y="-5%" width="104%" height="110%">
              <feTurbulence type="fractalNoise" baseFrequency="0.03" numOctaves="2" seed="4" result="n" />
              <feDisplacementMap in="SourceGraphic" in2="n" scale="2.6" />
            </filter>
            <filter id="rough" x="-5%" y="-5%" width="110%" height="110%">
              <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="2" result="n" />
              <feDisplacementMap in="SourceGraphic" in2="n" scale="1.4" />
            </filter>
          </defs>
        </svg>
        <LiveProvider>
          <GlossaryProvider entries={glossary}>
            <Masthead page={page} />
            <main className="page" id="main">{children}</main>
            <Footer />
          </GlossaryProvider>
        </LiveProvider>
      </body>
    </html>
  );
}
