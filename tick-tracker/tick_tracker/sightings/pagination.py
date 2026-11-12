from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"   # client can ask for ?page_size=100
    max_page_size = 500                   # ...but not 1,000,000