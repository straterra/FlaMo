var socket = io.connect();

//var socket = io.connect('https://dreamer.fuhell.com')



//refresh machine information
function refresh_machine_information() {
	$('#machine_name').text(flashforge.machine.name);
	$('#machine_type').text(flashforge.machine.type);
}

//refresh machine status
function refresh_machine_status() {
	switch (flashforge.machine.status) {
		case 'READY':
			$('#machine_state').text('Idling');
			break;
		case 'BUILDING_FROM_SD':
			$('#machine_state').text('Printing from SD Card ' + flashforge.machine.sdcard.progress.toString() + '%');
			break;
	}
}
var machine_state_uimap = {
};

//handle output from printer
socket.on('terminal', function(data) {
	$('#terminal').text($('#terminal').text() + data);
	$('#terminal').scrollTop($('#terminal')[0].scrollHeight);

        if ($('#terminal').val().length > 10000) {
                var cuttext = $('#terminal').text();
                $('#terminal').text(cuttext.substr(5000));
        }

	
	if (data.startsWith('< ')) {
		//update ui if neccessary
		command = flashforge.parse_data(data.substr(2));
		switch (command) {
			case 'M115': refresh_machine_information(); break;
			case 'M119':
				refresh_machine_status();
				break;
			case 'M27':
				refresh_machine_status();
				break;
			case 'M105': refresh_temps(); break;
			default: break;
		}
	}
});

//function to send gcode on form submit
$('#gcode_cmd_form').submit(function(e) {
	//don't send form to server
	e.preventDefault();
});


$(function() {

  var checkbox = $("#trigger");
  var hidden = $('#terminal');

  hidden.show();

  checkbox.change(function() {
    if (checkbox.is(':checked')) {
      hidden.hide();
    } else {
      hidden.show();
    }
  });
});