import { NoteSnoopApp } from "../../../components/notesnoop-app";

export default async function WorkflowPage({ params }: { params: Promise<{ workflowId: string }> }) {
  const { workflowId } = await params;
  return <NoteSnoopApp quickCapture={false} initialRoute={{ kind: "workflow", id: workflowId }} />;
}
