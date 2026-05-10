import { NoteSnoopApp } from "../../../components/notesnoop-app";

export default async function PersonPage({ params }: { params: Promise<{ personId: string }> }) {
  const { personId } = await params;
  return <NoteSnoopApp quickCapture={false} initialRoute={{ kind: "person", id: personId }} />;
}
