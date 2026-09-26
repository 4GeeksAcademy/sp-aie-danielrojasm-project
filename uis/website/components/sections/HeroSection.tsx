import { ButtonLink } from "@/components/ui/ButtonLink";
import { FramedImage } from "@/components/ui/FramedImage";
import type { HeroContent } from "@/types/site";

interface HeroSectionProps {
  content: HeroContent;
  applicationHref: string;
}

export function HeroSection({ content, applicationHref }: HeroSectionProps) {
  return (
    <section className="relative overflow-hidden" aria-labelledby="hero-title">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(34,211,238,0.2),transparent_60%)]" />
      <div className="mx-auto grid w-full max-w-7xl gap-10 px-4 py-16 sm:px-6 md:py-24 lg:grid-cols-2 lg:items-center lg:px-8">
        <div className="relative">
          <p className="mb-4 inline-flex rounded-full border border-cyan-300/30 bg-cyan-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.2em] text-cyan-100">
            {content.eyebrow}
          </p>
          <h1
            id="hero-title"
            className="text-4xl font-black leading-tight text-white sm:text-5xl lg:text-6xl"
          >
            {content.title}
          </h1>
          <p className="mt-6 max-w-xl text-base text-slate-300 sm:text-lg">
            {content.description}
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <ButtonLink href={applicationHref} ariaLabel="Comenzar aplicación">
              Comenzar aplicación
            </ButtonLink>
            <ButtonLink href="/#beneficios" variant="outline">
              Ver beneficios
            </ButtonLink>
          </div>
        </div>

        <div className="relative">
          <FramedImage image={content.image} priority />
          <div className="absolute -bottom-5 left-5 rounded-xl border border-emerald-300/30 bg-slate-900/95 p-4 shadow-xl">
            <p className="text-xs uppercase tracking-[0.2em] text-emerald-300">
              {content.highlight.label}
            </p>
            <p className="text-2xl font-extrabold text-white">
              {content.highlight.value}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
