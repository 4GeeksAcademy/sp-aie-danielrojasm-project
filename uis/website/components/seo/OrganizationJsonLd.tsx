import { company } from "@/content/site";

/** Datos estructurados schema.org (mismo contenido que el Hito 1). */
export function OrganizationJsonLd() {
  const jsonLd = {
    "@context": "https://schema.org",
    "@type": "Organization",
    name: company.name,
    url: company.url,
    logo: `${company.url}/logo.png`,
    description: company.description,
    foundingDate: String(company.foundingYear),
    numberOfEmployees: String(company.employees),
    email: company.email,
    telephone: company.phone,
    address: company.offices.map((office) => ({
      "@type": "PostalAddress",
      streetAddress: office.streetAddress,
      addressLocality: office.city,
      postalCode: office.postalCode,
      addressCountry: office.countryCode,
    })),
    sameAs: company.socialProfiles,
  };

  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
    />
  );
}
