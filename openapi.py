import json
import logging
import os.path
import typing

logger = logging.getLogger(__name__)


JsonFragment = typing.Dict[str, typing.Any]

class _OpenApiElement:
    def __init__(self, document: "Document", jsonpointer:str, jsonfragment: JsonFragment):
        self.document = document
        self.jsonpointer = jsonpointer
        self.raw_jsonfragment = jsonfragment
        self.jsonfragment = self.resolve(jsonfragment)

    def resolve(self, jsonfragment) -> JsonFragment:
        resolved = jsonfragment.copy()
        try:
            ref = resolved.pop("$ref")
            resolved.update(self.document.load_fragment(ref))
        except KeyError:
            pass
        return resolved


class Schema(_OpenApiElement):
    def __init__(
        self, document: "Document", jsonpointer:str, jsonfragment: JsonFragment
    ):
        super().__init__(document, jsonpointer, jsonfragment)
        if '$ref' in self.raw_jsonfragment:
            self.jsonpointer = self.raw_jsonfragment['$ref']
    
    @property
    def typename(self):
        try:
            return self.raw_jsonfragment["$ref"].split("/")[-1]
        except KeyError:
            return "?"


class BodyParameter(_OpenApiElement):
    def __init__(
        self, document: "Document", jsonpointer: str, jsonfragment: JsonFragment
    ):
        super().__init__(document, jsonpointer, jsonfragment)
        self.schema = Schema(document, jsonpointer + '/schema', self.jsonfragment["schema"])

    @property
    def typename(self):
        return self.schema.typename


class Response(_OpenApiElement):
    def __init__(
        self, document: "Document", jsonpointer: str, jsonfragment: typing.Dict[str, typing.Any]
    ):
        super().__init__(document, jsonpointer, jsonfragment)
        if "schema" in self.jsonfragment:
            self.schema: typing.Optional[Schema] = Schema(document, jsonpointer=jsonpointer + '/schema', jsonfragment=self.jsonfragment["schema"])
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


class ModelProperty(_OpenApiElement):
    def __init__(
        self,
        document: "Document",
        jsonpointer: str,
        name: str,
        jsonfragment: JsonFragment
    ):
        super().__init__(document, jsonpointer, jsonfragment)
        self.name = name
        
        self.typename = self.type_information(self.jsonfragment)
        if self.typename == 'array':
            self.itemtypename = self.type_information(self.jsonfragment['items'])
        else:
            self.itemtypename = None

        if self.typename in ['string', 'boolean', 'number', 'object']:
            self.typetype = 'scalar'
        else:
            self.typetype = 'model'

        self.properties = [
            ModelProperty(document, jsonpointer=self.jsonpointer + '/properties/' + name, name=name, jsonfragment=fragment)
            for name, fragment in self.jsonfragment.get('properties', {}).items()
        ]
            
    def type_information(self, raw_jsonfragment):
        if '$ref' in raw_jsonfragment:
            return raw_jsonfragment['$ref'].split('/')[-1]
        jsonfragment = self.document.resolve_fragment(raw_jsonfragment)
        if 'type' in jsonfragment:
            return jsonfragment['type']
        else:
            return 'huh?'

class Definition(_OpenApiElement):
    def __init__(
        self,
        document: "Document",
        jsonpointer: str,
        name: str,
        jsonfragment: JsonFragment
    ):
        super().__init__(document, jsonpointer, jsonfragment)
        self.typename = name
        self.properties = [
            ModelProperty(document=document, jsonpointer=jsonpointer + '/properties' + name, name=name, jsonfragment=fragment)
            for name, fragment in self.jsonfragment.get('properties', {}).items()
        ]

class Operation(_OpenApiElement):
    def __init__(
        self,
        document: "Document",
        jsonpointer: str,
        verb: str,
        jsonfragment: typing.Dict[str, typing.Any],
    ):
        super().__init__(document, jsonpointer, jsonfragment)
        self.verb = verb.upper()

        parameterjsonfragments = [
            fragment for fragment in self.jsonfragment.get("parameters", [])
        ]

        # Extract the body parameter. There is exactly zero or one body parameters...
        try:
            index, bodyparameterjsonfragment = next(enumerate([
                parameterjsonfragment
                for parameterjsonfragment in parameterjsonfragments
                if document.resolve_fragment(parameterjsonfragment).get("in", "")
                == "body"
            ]))
            self.body_parameter: typing.Optional[BodyParameter] = BodyParameter(document, jsonpointer=jsonpointer + f'[{index}]', jsonfragment=bodyparameterjsonfragment)
        except StopIteration:
            self.body_parameter = None

        # Extract query parameters...
        self.query_parameters = [
            QueryHeaderParameter(document, jsonpointer='unknown', jsonfragment=parameterjsonfragment)
            for parameterjsonfragment in parameterjsonfragments
            if document.resolve_fragment(parameterjsonfragment).get("in", "") == "query"
        ]

        self.header_parameters = [
            QueryHeaderParameter(document, jsonpointer='unknown', jsonfragment=parameterjsonfragment)
            for parameterjsonfragment in parameterjsonfragments
            if document.resolve_fragment(parameterjsonfragment).get("in", "")
            == "header"
        ]

        self.path_parameters = [
            QueryHeaderParameter(document, jsonpointer='unknown', jsonfragment=parameterjsonfragment)
            for parameterjsonfragment in parameterjsonfragments
            if document.resolve_fragment(parameterjsonfragment).get("in", "") == "path"
        ]

        return_values = [
            Response(document, jsonpointer=self.jsonpointer + f'/{status_code}', jsonfragment=returnvaluefragment)
            for status_code, returnvaluefragment in self.jsonfragment.get(
                "responses", {}
            ).items()
            if status_code != "default"
            and "x-ms-error-response"
            not in document.resolve_fragment(returnvaluefragment)
        ]
        if len(return_values):
            if len(return_values) > 1:
                logger.warn("Multiple return values for operation '%s'", self.name)
            self.return_value: typing.Union[Response, VoidResponse] = return_values[0]
        else:
            self.return_value = VoidResponse()

    @property
    def name(self):
        return self.jsonfragment.get("operationId", "<Unknown>")


class Path(_OpenApiElement):
    def __init__(
        self, document: "Document", jsonpointer, name: str, jsonfragment: typing.Dict[str, typing.Any]
    ):
        super().__init__(document, jsonpointer, jsonfragment)
        self.name = name

        self.operations = [
            Operation(document, jsonpointer=jsonpointer + f'/{verb}', verb=verb, jsonfragment=fragment)
            for verb, fragment in self.jsonfragment.items()
        ]


class Document:
    def __init__(self, file_path):
        self.file_path = os.path.abspath(file_path)
        self.jsonfragment = self.load_fragment("#/")
        self.paths = [
            Path(self, jsonpointer=f'#/paths/{name}', name=name, jsonfragment=fragment)
            for name, fragment in self.jsonfragment.get("paths", {}).items()
        ]
        self.definitions = [
            Definition(self, jsonpointer=f'#/definitions/{name}', name=name, jsonfragment=fragment)
            for name, fragment in self.jsonfragment.get('definitions', {}).items()
        ]

    def _extract_references(self):
        """Extract "resource definitions" - that is, definitions that are direct inputs or outputs
        of operations.
        """
        references = []
        for path in self.paths:
            for operation in path.operations:
                if operation.return_value:
                    if operation.return_value.schema:
                        references.append(('out', operation.return_value.schema.jsonpointer))
                    else:
                        references.append(('out', operation.return_value.jsonpointer))
                if operation.body_parameter:
                    if operation.body_parameter.schema:
                        references.append(('in', operation.body_parameter.schema.jsonpointer))
                    else:
                        references.append(('in', operation.body_parameter.jsonpointer))

        return set(references)

    @property
    def inputdefinitions(self):
        jsonpointers = [jsonpointer for direction, jsonpointer in self._extract_references() if direction == 'in']
        return [definition for definition in self.definitions if definition.jsonpointer in jsonpointers]

    @property
    def outputdefinitions(self):
        jsonpointers = [jsonpointer for direction, jsonpointer in self._extract_references() if direction == 'out']
        return [definition for definition in self.definitions if definition.jsonpointer in jsonpointers]

    @property
    def supportdefinitions(self):
        jsonpointers = [jsonpointer for direction, jsonpointer in self._extract_references()]
        return [definition for definition in self.definitions if definition.jsonpointer not in jsonpointers]

    @property
    def resourcedefinitions(self):
        jsonpointers = [jsonpointer for direction, jsonpointer in self._extract_references()]
        return [definition for definition in self.definitions if definition.jsonpointer in jsonpointers]

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

    print(doc.inputdefinitions)

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
