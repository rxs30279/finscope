import CompanyClient from "./_client";

interface PageProps {
  searchParams: Promise<{ symbol?: string; tab?: string }>;
}

export default async function CompanyPage({ searchParams }: PageProps) {
  const { symbol = "", tab } = await searchParams;
  return <CompanyClient symbol={decodeURIComponent(symbol)} initialTab={tab} />;
}
