import { NoteSnoopApp } from "../../../components/notesnoop-app";

export default async function MeetingPage({ params }: { params: Promise<{ meetingId: string }> }) {
  const { meetingId } = await params;
  return <NoteSnoopApp quickCapture={false} initialRoute={{ kind: "meeting", id: meetingId }} />;
}
