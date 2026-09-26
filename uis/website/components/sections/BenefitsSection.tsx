import { FeatureCard } from "@/components/ui/FeatureCard";
import { FramedImage } from "@/components/ui/FramedImage";
import type { FeatureItem, ImageAsset } from "@/types/site";

interface BenefitsSectionProps {
  benefits: FeatureItem[];
  image: ImageAsset;
}

export function BenefitsSection({ benefits, image }: BenefitsSectionProps) {
  return (
    <section
      id="beneficios"
      className="scroll-mt-24 border-y border-slate-800 bg-slate-900/60"
      aria-labelledby="beneficios-title"
    >
      <div className="mx-auto grid w-full max-w-7xl gap-10 px-4 py-16 sm:px-6 lg:grid-cols-2 lg:items-center lg:px-8">
        <div>
          <h2
            id="beneficios-title"
            className="text-3xl font-extrabold text-white sm:text-4xl"
          >
            Por qué las marcas eligen TrackFlow
          </h2>
          <ul className="mt-8 space-y-4" aria-label="Beneficios principales">
            {benefits.map((benefit) => (
              <li key={benefit.title}>
                <FeatureCard item={benefit} variant="compact" />
              </li>
            ))}
          </ul>
        </div>
        <FramedImage image={image} />
      </div>
    </section>
  );
}
