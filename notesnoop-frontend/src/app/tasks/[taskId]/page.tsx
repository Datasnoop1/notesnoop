import { NoteSnoopApp } from "../../../components/notesnoop-app";

export default async function TaskPage({ params }: { params: Promise<{ taskId: string }> }) {
  const { taskId } = await params;
  return <NoteSnoopApp quickCapture={false} initialRoute={{ kind: "task", id: taskId }} />;
}
