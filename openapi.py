import json
import logging
import os.path
import typing

logger = logging.getLogger(__name__)


class _OpenApiElement:
    def __init__(self, document, jsonfragment):
        self.document = document
        self.raw_jsonfragment = jsonfragment
        self.jsonfragment = self.resolve(jsonfragment)

    def resolve(self, jsonfragment):
        resolved = jsonfragment.copy()
        try:
            ref = resolved.pop("$ref")
            resolved.update(self.document.load_fragment(ref))
        except KeyError:
            pass
        return resolved


class Schema:
    def __init__(
        self, document: "Document", jsonfragment: typing.Dict[str, typing.Any]
    ):
        self.document = document
        self.jsonfragment = jsonfragment

    @property
    def typename(self):
        try:
            return self.jsonfragment["$ref"].split("/")[-1]
        except KeyError:
            return "?"


class BodyParameter(_OpenApiElement):
    def __init__(
        self, document: "Document", jsonfragment: typing.Dict[str, typing.Any]
    ):
        super().__init__(document, jsonfragment)
        self.schema = Schema(document, self.jsonfragment["schema"])

    @property
    def typename(self):
        return self.schema.typename


class Response(_OpenApiElement):
    def __init__(
        self, document: "Document", jsonfragment: typing.Dict[str, typing.Any]
    ):
        super().__init__(document, jsonfragment)
        if "schema" in self.jsonfragment:
            self.schema: typing.Optional[Schema] = Schema(document, self.jsonfragment["schema"])
        else:
            self.schema = None

    @property
    def typename(self):
        if self.schema:
            return self.schema.typename
        else:
            return "void"

class VoidResponse:

    typename = "void"

class QueryHeaderParameter(_OpenApiElement):
    @property
    def typename(self):
        typename = self.jsonfragment.get("type", "")
        if typename == "array":
            itemtypename = self.jsonfragment["items"]
            return "[" + itemtypename + "]"
        else:
            return typename

    @property
    def name(self):
        return self.jsonfragment["name"]


class Definition:
    def __init__(
        self,
        document: "Document",
        name: str,
        jsonfragment: typing.Dict[str, typing.Any]
    ):
        self.typename = name



class Operation:
    def __init__(
        self,
        document: "Document",
        verb: str,
        jsonfragment: typing.Dict[str, typing.Any],
    ):
        self.document = document
        self.verb = verb.upper()
        self.jsonfragment = jsonfragment

        parameterjsonfragments = [
            fragment for fragment in self.jsonfragment.get("parameters", [])
        ]

        # Extract the body parameter. There is exactly zero or one body parameters...
        try:
            bodyparameterjsonfragment = [
                parameterjsonfragment
                for parameterjsonfragment in parameterjsonfragments
                if document.resolve_fragment(parameterjsonfragment).get("in", "")
                == "body"
            ][0]
            self.body_parameter: typing.Optional[BodyParameter] = BodyParameter(document, bodyparameterjsonfragment)
        except IndexError:
            self.body_parameter = None

        # Extract query parameters...
        self.query_parameters = [
            QueryHeaderParameter(document, parameterjsonfragment)
            for parameterjsonfragment in parameterjsonfragments
            if document.resolve_fragment(parameterjsonfragment).get("in", "") == "query"
        ]

        self.header_parameters = [
            QueryHeaderParameter(document, parameterjsonfragment)
            for parameterjsonfragment in parameterjsonfragments
            if document.resolve_fragment(parameterjsonfragment).get("in", "")
            == "header"
        ]

        self.path_parameters = [
            QueryHeaderParameter(document, parameterjsonfragment)
            for parameterjsonfragment in parameterjsonfragments
            if document.resolve_fragment(parameterjsonfragment).get("in", "") == "path"
        ]

        return_values = [
            Response(document, returnvaluefragment)
            for status_code, returnvaluefragment in self.jsonfragment.get(
                "responses", {}
            ).items()
            if status_code != "default"
            and "x-ms-error-response"
            not in document.resolve_fragment(returnvaluefragment)
        ]
        if len(return_values):
            if len(return_values) > 1:
                logger.warn("Multiple return values for operation {}", self.name)
            self.return_value: typing.Union[Response, VoidResponse] = return_values[0]
        else:
            self.return_value = VoidResponse()

    @property
    def name(self):
        return self.jsonfragment.get("operationId", "<Unknown>")


class Path:
    def __init__(
        self, document: "Document", name: str, fragment: typing.Dict[str, typing.Any]
    ):
        self.document = document
        self.name = name
        self.jsonfragment = fragment

        self.operations = [
            Operation(document, name, fragment)
            for name, fragment in self.jsonfragment.items()
        ]


class Document:
    def __init__(self, file_path):
        self.file_path = os.path.abspath(file_path)
        self.jsonfragment = self.load_fragment("#/")
        self.paths = [
            Path(self, name, fragment)
            for name, fragment in self.jsonfragment.get("paths", {}).items()
        ]
        self.definitions = [
            Definition(self, name, fragment)
            for name, fragment in self.jsonfragment.get('definitions', {}).items()
        ]

    def resolve_fragment(
        self, fragment: typing.Dict[str, typing.Any]
    ) -> typing.Dict[str, typing.Any]:
        resolved = fragment.copy()
        ref = resolved.get("$ref", None)
        if ref:
            resolved.update(self.load_fragment(ref))
        return resolved

    def load_fragment(self, jsonpointer: str) -> typing.Dict[str, typing.Any]:
        filepathjsonpointer, localjsonpointer = jsonpointer.split("#/", maxsplit=2)

        if filepathjsonpointer in (".", "", "./"):
            file_path = self.file_path
        elif not os.path.isabs(filepathjsonpointer):
            file_path = os.path.join(os.path.dirname(self.file_path), file_path)
        else:
            file_path = filepathjsonpointer

        with open(file_path, mode="r", encoding="utf8") as f:
            document = json.load(f)

        for part in localjsonpointer.split("/"):
            if part:
                document = document[part]
        return document


if __name__ == "__main__":
    import sys

    logging.basicConfig()

    doc = Document(sys.argv[1])

    for path in doc.paths:
        print(path.name)
        for operation in path.operations:
            body = (
                f"body {operation.body_parameter.typename}"
                if operation.body_parameter
                else ""
            )
            query = (
                f"query " + ", ".join([qp.name for qp in operation.query_parameters])
                if operation.query_parameters
                else ""
            )
            headers = (
                f"header " + ", ".join([qp.name for qp in operation.header_parameters])
                if operation.header_parameters
                else ""
            )
            paths = (
                f"path " + ", ".join([pp.name for pp in operation.path_parameters])
                if operation.path_parameters
                else ""
            )
            parameters = ", ".join(
                [part for part in (paths, body, query, headers) if part]
            )
            print(f"\t{operation.verb} {operation.name}({parameters})")
