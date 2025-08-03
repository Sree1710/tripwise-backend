from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from io import BytesIO

def generate_itinerary_pdf(itinerary_data):
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, height - 50, "TripWise AI - Travel Itinerary")

    pdf.setFont("Helvetica", 10)
    summary = itinerary_data.get("summary", {})
    y = height - 80

    pdf.drawString(50, y, f"Start Date: {summary.get('start_date', '')}")
    pdf.drawString(200, y, f"End Date: {summary.get('end_date', '')}")
    pdf.drawString(400, y, f"Total Days: {summary.get('total_days', '')}")
    y -= 20
    pdf.drawString(50, y, f"Budget: Rs.{summary.get('proposed_budget', '')}")
    pdf.drawString(200, y, f"Predicted: Rs.{summary.get('predicted_budget', '')}")
    pdf.drawString(400, y, f"Actual: Rs.{summary.get('actual_cost', '')}")
    y -= 30

    for day, activities in itinerary_data.get("day_wise_itinerary", {}).items():
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(50, y, day)
        y -= 20
        pdf.setFont("Helvetica", 10)
        for act in activities:
            line = f"{act.get('time')} - {act.get('activity')}"
            duration = act.get("duration_hours")
            weather = act.get("weather", {}).get("condition")
            if duration:
                line += f" ({duration} hr)"
            if weather:
                line += f" - Weather: {weather}"
            pdf.drawString(60, y, line)
            y -= 15
            if y < 50:
                pdf.showPage()
                y = height - 50

        y -= 10

    pdf.save()
    buffer.seek(0)
    return buffer
