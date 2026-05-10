import { NoteSnoopApp } from "../../../components/notesnoop-app";

export default async function CompanyPage({ params }: { params: Promise<{ companyId: string }> }) {
  const { companyId } = await params;
  return <NoteSnoopApp quickCapture={false} initialRoute={{ kind: "company", id: companyId }} />;
}
