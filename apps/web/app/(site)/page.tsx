import { Hero } from "@/components/landing/Hero";
import { WhyUseIt } from "@/components/landing/WhyUseIt";
import { FeatureHighlights } from "@/components/landing/FeatureHighlights";
import { CtaSection } from "@/components/landing/CtaSection";

export default function Home() {
  return (
    <main className="flex flex-col">
      <Hero />
      <WhyUseIt />
      <FeatureHighlights />
      <CtaSection />
    </main>
  );
}
