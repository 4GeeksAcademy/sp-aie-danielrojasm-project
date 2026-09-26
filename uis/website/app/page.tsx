import { BenefitsSection } from "@/components/sections/BenefitsSection";
import { ContactSection } from "@/components/sections/ContactSection";
import { HeroSection } from "@/components/sections/HeroSection";
import { ServicesSection } from "@/components/sections/ServicesSection";
import { OrganizationJsonLd } from "@/components/seo/OrganizationJsonLd";
import {
  APPLICATION_PATH,
  benefits,
  benefitsImage,
  company,
  contactCta,
  hero,
  services,
  servicesIntro,
} from "@/content/site";

export default function HomePage() {
  return (
    <>
      <OrganizationJsonLd />
      <HeroSection content={hero} applicationHref={APPLICATION_PATH} />
      <ServicesSection intro={servicesIntro} services={services} />
      <BenefitsSection benefits={benefits} image={benefitsImage} />
      <ContactSection
        title={contactCta.title}
        description={contactCta.description}
        email={company.email}
        applicationHref={APPLICATION_PATH}
      />
    </>
  );
}
