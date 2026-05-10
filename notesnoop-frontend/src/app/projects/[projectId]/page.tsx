import { NoteSnoopApp } from "../../../components/notesnoop-app";

export default async function ProjectPage({ params }: { params: Promise<{ projectId: string }> }) {
  const { projectId } = await params;
  return <NoteSnoopApp quickCapture={false} initialRoute={{ kind: "project", id: projectId }} />;
}
