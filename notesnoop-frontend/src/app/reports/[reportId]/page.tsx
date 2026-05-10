import { NoteSnoopApp } from "../../../components/notesnoop-app";

export default async function ReportPage({ params }: { params: Promise<{ reportId: string }> }) {
  const { reportId } = await params;
  return <NoteSnoopApp quickCapture={false} initialRoute={{ kind: "report", id: reportId }} />;
}
