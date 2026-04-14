"use client";
import { Download, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ExportButtonsProps {
  onExportCSV?: () => void;
  onPrint?: () => void;
  label?: string;
}

export default function ExportButtons({ onExportCSV, onPrint, label = "Export" }: ExportButtonsProps) {
  return (
    <div className="flex gap-1">
      {onExportCSV && (
        <Button variant="outline" size="sm" onClick={onExportCSV} className="text-[10px] h-7 px-2">
          <Download className="w-3 h-3 mr-1" /> CSV
        </Button>
      )}
      {onPrint && (
        <Button variant="outline" size="sm" onClick={onPrint} className="text-[10px] h-7 px-2">
          <Printer className="w-3 h-3 mr-1" /> Print
        </Button>
      )}
    </div>
  );
}
