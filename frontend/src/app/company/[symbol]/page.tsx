import CompanyClient from "./_client";

interface PageProps {
  params: Promise<{ symbol: string }>;
  searchParams: Promise<{ tab?: string }>;
}

export default async function CompanyPage({ params, searchParams }: PageProps) {
  const { symbol } = await params;
  const { tab } = await searchParams;
  return (
    <CompanyClient symbol={decodeURIComponent(symbol)} initialTab={tab} />
  );
}
