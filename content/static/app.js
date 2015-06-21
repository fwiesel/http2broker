function select_backend(item) {
    var state = item.getAttribute('state');
    if (state === 'selected') {
        item.removeAttribute('state');
        item.event_source.close();
        item.event_source = null;
    }
    else {
        item.setAttribute('state', 'selected');
        var source = new EventSource('/q/'.concat(item.id));
        var streamNode = document.getElementById('stream');
        var tableNode = streamNode.parentNode;
        source.onmessage = function(event) {

            var sourceText = document.createTextNode(item.id);
            var source = document.createElement('td');
            source.appendChild(sourceText);

            var message = document.createElement('td');
            var messageText = document.createTextNode(event.data);
            message.appendChild(messageText);

            var line = document.createElement('tr');
            line.appendChild(source);
            line.appendChild(message);
            stream.appendChild(line);
            tableNode.scrollTop = line.offsetTop;
            console.log(line.offsetTop);
            if (line.offsetTop > 10*screen.height) {
                streamNode.removeChild(streamNode.firstChild);
            }
        };
        item.event_source = source;
    }
}

function send_message(item) {
    var message = item.parentNode.querySelector('#txtSend').value;
    var items = document.getElementById('backend').querySelectorAll('[state=selected]');
    for (var i = 0; i < items.length; ++i) {
        var item = items[i];
        var request = new XMLHttpRequest();
        request.open('PUT', '/q/' + item.id + '/?m=' + encodeURIComponent(message), true);
        // request.setRequestHeader('content-type', 'text/plain');
        // request.send(message);
        request.send();
    }

}