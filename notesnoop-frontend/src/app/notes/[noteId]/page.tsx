import { NoteSnoopApp } from "../../../components/notesnoop-app";

export default async function NotePage({ params }: { params: Promise<{ noteId: string }> }) {
  const { noteId } = await params;
  return <NoteSnoopApp quickCapture={false} initialRoute={{ kind: "note", id: noteId }} />;
}
