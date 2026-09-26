import { FeatureCard } from "@/components/ui/FeatureCard";
import { SectionHeading } from "@/components/ui/SectionHeading";
import type { FeatureItem } from "@/types/site";

interface ServicesSectionProps {
  intro: string;
  services: FeatureItem[];
}

export function ServicesSection({ intro, services }: ServicesSectionProps) {
  return (
    <section
      id="servicios"
      className="mx-auto w-full max-w-7xl scroll-mt-24 px-4 py-16 sm:px-6 lg:px-8"
      aria-labelledby="servicios-title"
    >
      <SectionHeading
        id="servicios-title"
        title="Lo que hacemos por tu operación"
        description={intro}
      />
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
        {services.map((service) => (
          <FeatureCard key={service.title} item={service} />
        ))}
      </div>
    </section>
  );
}
