from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import FileResponse
from .utils.pdf_generator import generate_itinerary_pdf

class ExportPDFView(APIView):
    def post(self, request):
        try:
            itinerary_data = request.data
            pdf_buffer = generate_itinerary_pdf(itinerary_data)
            return FileResponse(pdf_buffer, as_attachment=True, filename="itinerary.pdf")
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
