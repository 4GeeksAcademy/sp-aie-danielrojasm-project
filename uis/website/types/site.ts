export interface NavLink {
  label: string;
  href: string;
}

export interface FeatureItem {
  title: string;
  description: string;
}

export interface ImageAsset {
  src: string;
  alt: string;
}

export interface Office {
  city: string;
  region: string;
  country: string;
  streetAddress: string;
  postalCode: string;
  countryCode: "US" | "ES";
}

export interface HeroContent {
  eyebrow: string;
  title: string;
  description: string;
  image: ImageAsset;
  highlight: { label: string; value: string };
}

export interface CompanyInfo {
  name: string;
  tagline: string;
  description: string;
  url: string;
  email: string;
  phone: string;
  phoneDisplay: string;
  foundingYear: number;
  employees: number;
  offices: Office[];
  socialProfiles: string[];
}
