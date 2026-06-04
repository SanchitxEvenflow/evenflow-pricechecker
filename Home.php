<?php
if (!defined('BASEPATH'))exit('No direct script access allowed');

use PhpOffice\PhpSpreadsheet\Spreadsheet;
use PhpOffice\PhpSpreadsheet\Writer\Xlsx;

class Home extends CI_Controller 
{
	public function __construct() 
	{
        parent::__construct();
		$this->load->model('HomeModel');
		$this->load->database();
		$this->load->helper(array('form','url'));
        $this->load->library(array('session', 'form_validation', 'email'));
    } 
	
	public function index() 
	{
		
		$data['get_count'] = $this->HomeModel->get_count_homeSection1();
		//restrict users to go to home if not logged in
		if($this->session->userdata('user'))
		{
			$this->load->view('layout/header_data');
			$this->load->view('layout/left_side_bar');
			$this->load->view('home-page/home_page_list', $data);
			$this->load->view('layout/footer_data');
		}
		else
		{
			redirect('admin-login');
		}
    }
	
	/*public function createExcel() 
	{
		$fileName = 'employeefeedback.xlsx';  
		$employeeData = $this->EmployeeModel->employeeList();
		
		$spreadsheet = new Spreadsheet();
        $sheet = $spreadsheet->getActiveSheet();
        $sheet->setCellValue('A1', 'Hello World !');
		$sheet->setCellValue('A1', 'Id');
        $sheet->setCellValue('B1', 'Comment1');
        $sheet->setCellValue('C1', 'Comment2');
        $sheet->setCellValue('D1', 'Department');
		$sheet->setCellValue('E1', 'Feedback');
        //$sheet->setCellValue('F1', 'Designation');       
        $rows = 2;
		
        foreach ($employeeData as $val)
		{
            $sheet->setCellValue('A' . $rows, $val['id']);
            $sheet->setCellValue('B' . $rows, $val['comment1']);
            $sheet->setCellValue('C' . $rows, $val['comment2']);
            $sheet->setCellValue('D' . $rows, $val['department']);
			$sheet->setCellValue('E' . $rows, $val['feedback']);
            //$sheet->setCellValue('F' . $rows, $val['designation']);
            $rows++;
        } 
		
        $writer = new Xlsx($spreadsheet);
		$writer->save("upload/".$fileName);
		header("Content-Type: application/vnd.ms-excel");
        redirect(base_url()."/upload/".$fileName);              
    }

	// Export data in CSV format 
	public function exportCSV()
	{ 
		// file name 
		$filename = 'employeefeedback_'.date('Ymd').'.csv'; 
		header("Content-Description: File Transfer"); 
		header("Content-Disposition: attachment; filename=$filename"); 
		header("Content-Type: application/csv; ");
	   
		// get data 
		$usersData = $this->EmployeeModel->getUserDetails();

		// file creation 
		$file = fopen('php://output', 'w');
	 
		$header = array("Id","Comment1","Comment2","Department", "Feedback"); 
		fputcsv($file, $header);
		foreach ($usersData as $key=>$line)
		{ 
			fputcsv($file,$line); 
		}
		fclose($file); 
		exit; 
	}*/
	//For Home Section1
	public function section1() 
	{
		$data['get_count'] = $this->HomeModel->get_count_homeSection1();
        if($this->session->userdata('user'))
		{
			$data['homeSection1'] = $this->HomeModel->HomeSection1List();
		    $this->load->view('layout/header_data');
			$this->load->view('layout/left_side_bar');
			$this->load->view('home-page/home_page_list', $data);
			$this->load->view('layout/footer_data');
		}
		else
		{
			redirect('admin-login');
		}
    }
	
	
	public function add_home_section1()
    {
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page/add');
		$this->load->view('layout/footer_data');
    }
	
    public function save_home_page_section1()
    {
		//print_r($_POST);
		//die;
		$RequestMethod = $this->input->server('REQUEST_METHOD');
        if($RequestMethod == "POST")  
		{ 
			 $img_name=$this->HomeModel->banner_images_upload();
			 $image_name=$img_name['file_name'];
			 //echo $image_name;
			 //die;
			 $data=array(
		   'heading1'=>$this->input->post('heading1'),	              
		   'heading2'=>$this->input->post('heading2'),
		   'description'=>$this->input->post('description'),	               
		   'banner_image'=>$image_name,
		   );
          
			
			$success = $this->db->insert('home_section1', $data);
				$this->session->set_flashdata('success','Successfully added...');
         
				//$this->session->set_flashdata('alert', array('message' => 'Successfully added...','class' => 'success'));
				redirect('home/section1');
		   }
    }
	
	public function delete_section1($section_id = null)
	{
		$this->HomeModel->delete_section1($section_id);
		$this->session->set_flashdata('success','Successfully Deleted...');
        redirect('home/section1');
	}
	
	
	public function edit_home_page_section1()
    {	
    
        $home_section1_id =  $this->uri->segment(3);
        $data['edit_home_section1'] = $this->HomeModel->get_home_page_section1_data($home_section1_id);
        //printarray($content['edit_data']['data']); die; 
        //$content['subview']="marketing-email/edit";
        //$this->load->view('main-layout/layout', $content);
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page/edit', $data);
		$this->load->view('layout/footer_data');
		
    }
	
	
	function update_home_page_section1(){
			
			   //$id=$this->uri->segment(3);
			   $RequestMethod = $this->input->server('REQUEST_METHOD');

                 if($RequestMethod == "POST")  { 
                 	$section_id=$this->input->post('section_id');
			         if($_FILES['banner_image']['name']=='') {
			               $image_name=$this->input->post('old_banner_image');
			               
		                  } else	{
							 /*$gallery_detais=$this->Product_Model->get_single_image($id);
				             $previous_name=$gallery_detais[0]->galley_image_name;
							 $img_file=FCPATH . '/webroot/uploads/gallery/'.$previous_name;
							 if (!unlink($img_file)) {} else { }*/
		                         $img_name=$this->HomeModel->banner_images_upload();
		        			 $image_name=$img_name['file_name'];
		        
						  }

				$data=array(
				'heading1'=>$this->input->post('heading1'),			
				'heading2'=>$this->input->post('heading2'),
				'description'=>$this->input->post('description'),			
				'banner_image'=>$image_name,
				);
				 
						
							$this->db->where('id',$section_id);
							$this->db->update('home_section1',$data);
							$this->session->set_flashdata('success','Successfully updated...');
         
							//$this->session->set_flashdata('alert', array('message' => 'Successfully updated... ','class' => 'success'));
							redirect('home/section1');
			   
			            }
	 	}
		
		
		
		//For Home Section 2
		
	public function section2() 
	{
		$data['get_count'] = $this->HomeModel->get_count_homeSection2();
        if($this->session->userdata('user'))
		{
			$data['homeSection2'] = $this->HomeModel->HomeSection2List();
		    $this->load->view('layout/header_data');
			$this->load->view('layout/left_side_bar');
			$this->load->view('home-page2/home_page_list', $data);
			$this->load->view('layout/footer_data');
		}
		else
		{
			redirect('admin-login');
		}
    }
	
	
	public function add_home_section2()
    {
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page2/add');
		$this->load->view('layout/footer_data');
    }
	
    public function save_home_page_section2()
    {
		//print_r($_POST);
		//die;
		$RequestMethod = $this->input->server('REQUEST_METHOD');
        if($RequestMethod == "POST")  
		{ 
			 $data=array(
			  'description'=>$this->input->post('description'),		   
		   );
          
			
			$success = $this->db->insert('home_section2', $data);
				$this->session->set_flashdata('success','Successfully added...');
         
				//$this->session->set_flashdata('alert', array('message' => 'Successfully added...','class' => 'success'));
				redirect('home/section2');
		   }
	
    }
	
	public function delete_section2($section_id = null)
	{
		$this->HomeModel->delete_section2($section_id);
		$this->session->set_flashdata('success','Successfully deleted...');
         
		redirect('home/section2');
	}
	
	
	public function edit_home_page_section2()
    {	
    
        $home_section2_id =  $this->uri->segment(3);
        $data['edit_home_section2'] = $this->HomeModel->get_home_page_section2_data($home_section2_id);
        $this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page2/edit', $data);
		$this->load->view('layout/footer_data');
		
    }
	
	
	function update_home_page_section2(){
			
			   //$id=$this->uri->segment(3);
			   $RequestMethod = $this->input->server('REQUEST_METHOD');

                 if($RequestMethod == "POST")  { 
                 	$section_id=$this->input->post('section_id');
				$data=array(
				'description'=>$this->input->post('description'),		   
				
				);
				 
						
							$this->db->where('id',$section_id);
							$this->db->update('home_section2',$data);
							$this->session->set_flashdata('success','Successfully updated...');
         
							//$this->session->set_flashdata('alert', array('message' => 'Successfully updated... ','class' => 'success'));
							redirect('home/section2');
			   
			            }
	 	}
		
		
		//For Home Section 3
		
		
		public function section3() 
		{
			$data['get_count'] = $this->HomeModel->get_count_homeSection3();
			if($this->session->userdata('user'))
			{
				$data['homeSection3'] = $this->HomeModel->HomeSection3List();
				$this->load->view('layout/header_data');
				$this->load->view('layout/left_side_bar');
				$this->load->view('home-page3/home_page_list', $data);
				$this->load->view('layout/footer_data');
			}
			else
			{
				redirect('admin-login');
			}
		}
	
	
	public function add_home_section3()
    {
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page3/add');
		$this->load->view('layout/footer_data');
    }
	
    public function save_home_page_section3()
    {
		//print_r($_POST);
		//die;
		$RequestMethod = $this->input->server('REQUEST_METHOD');
        if($RequestMethod == "POST")  
		{ 
			 $img_name=$this->HomeModel->home_section3_images_upload();
			 $image_name=$img_name['file_name'];
			 //echo $image_name;
			 //die;
			 $data=array(
			
			'main_heading'=>$this->input->post('main_heading'),
			'main_description'=>$this->input->post('main_description'),
			'heading1'=>$this->input->post('heading1'),
			'description1'=>$this->input->post('description1'),
			'heading2'=>$this->input->post('heading2'),
			'description2'=>$this->input->post('description2'),
			'heading3'=>$this->input->post('heading3'),
			'description3'=>$this->input->post('description3'),
			'banner_image'=>$image_name,
			);
          
			
			$success = $this->db->insert('home_section3', $data);
				$this->session->set_flashdata('success','Successfully added...');
         
				//$this->session->set_flashdata('alert', array('message' => 'Successfully added...','class' => 'success'));
				redirect('home/section3');
		   }
    }
	
	public function delete_section3($section_id = null)
	{
		$this->HomeModel->delete_section3($section_id);
		$this->session->set_flashdata('success','Successfully deleted...');
         
		redirect('home/section3');
	}
	
	
	public function edit_home_page_section3()
    {	
    
        $home_section3_id =  $this->uri->segment(3);
        $data['edit_home_section3'] = $this->HomeModel->get_home_page_section3_data($home_section3_id);
        $this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page3/edit', $data);
		$this->load->view('layout/footer_data');
		
    }
	
	
	function update_home_page_section3(){
			
			   //$id=$this->uri->segment(3);
			   $RequestMethod = $this->input->server('REQUEST_METHOD');

                 if($RequestMethod == "POST")  { 
                 	$section_id=$this->input->post('section_id');
			         if($_FILES['banner_image']['name']=='') {
			               $image_name=$this->input->post('old_banner_image');
			               
		                  } else	{
							 /*$gallery_detais=$this->Product_Model->get_single_image($id);
				             $previous_name=$gallery_detais[0]->galley_image_name;
							 $img_file=FCPATH . '/webroot/uploads/gallery/'.$previous_name;
							 if (!unlink($img_file)) {} else { }*/
		                     $img_name=$this->HomeModel->home_section3_images_upload();
		        			 $image_name=$img_name['file_name'];
		        
						  }

				$data=array(
				'main_heading'=>$this->input->post('main_heading'),
				'main_description'=>$this->input->post('main_description'),
				'heading1'=>$this->input->post('heading1'),
				'description1'=>$this->input->post('description1'),
				'heading2'=>$this->input->post('heading2'),
				'description2'=>$this->input->post('description2'),
				'heading3'=>$this->input->post('heading3'),
				'description3'=>$this->input->post('description3'),
				'banner_image'=>$image_name,
				
			
				);
				 
						
							$this->db->where('id',$section_id);
							$this->db->update('home_section3',$data);
							$this->session->set_flashdata('success','Successfully updated...');
         
							//$this->session->set_flashdata('alert', array('message' => 'Successfully updated... ','class' => 'success'));
							redirect('home/section3');
			   
			            }
	 	}
		
		//For Home Section4
		
		public function section4() 
	{
		$data['get_count'] = $this->HomeModel->get_count_homeSection4();
        if($this->session->userdata('user'))
		{
			$data['homeSection4'] = $this->HomeModel->HomeSection4List();
		    $this->load->view('layout/header_data');
			$this->load->view('layout/left_side_bar');
			$this->load->view('home-page4/home_page_list', $data);
			$this->load->view('layout/footer_data');
		}
		else
		{
			redirect('admin-login');
		}
    }
	
	
	public function add_home_section4()
    {
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page4/add');
		$this->load->view('layout/footer_data');
    }
	
    public function save_home_page_section4()
    {
		//print_r($_POST);
		//die;
		$RequestMethod = $this->input->server('REQUEST_METHOD');
        if($RequestMethod == "POST")  
		{ 
			 $data=array(
			
			'heading1'=>$this->input->post('heading1'),
			'heading2'=>$this->input->post('heading2'),
			'description'=>$this->input->post('description'),	               
		   );
          
			
			$success = $this->db->insert('home_section4', $data);
				$this->session->set_flashdata('success','Successfully added...');
         
				//$this->session->set_flashdata('alert', array('message' => 'Successfully added...','class' => 'success'));
				redirect('home/section4');
		   }
    }
	
	public function delete_section4($section_id = null)
	{
		$this->HomeModel->delete_section4($section_id);
		$this->session->set_flashdata('success','Successfully deleted...');
         
		redirect('home/section4');
	}
	
	
	public function edit_home_page_section4()
    {	
    
        $home_section4_id =  $this->uri->segment(3);
        $data['edit_home_section4'] = $this->HomeModel->get_home_page_section4_data($home_section4_id);
        $this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page4/edit', $data);
		$this->load->view('layout/footer_data');
		
    }
	
	
	function update_home_page_section4(){
			
			   //$id=$this->uri->segment(3);
			   $RequestMethod = $this->input->server('REQUEST_METHOD');

                 if($RequestMethod == "POST")  { 
                 	$section_id=$this->input->post('section_id');
			         

				$data=array(
				'heading1'=>$this->input->post('heading1'),
				'heading2'=>$this->input->post('heading2'),
				'description'=>$this->input->post('description'),	               
		   	
			
				);
				 
						
							$this->db->where('id',$section_id);
							$this->db->update('home_section4',$data);
							$this->session->set_flashdata('success','Successfully updated...');
         
							//$this->session->set_flashdata('alert', array('message' => 'Successfully updated... ','class' => 'success'));
							redirect('home/section4');
			   
			            }
	 	}
		
		
		
		//For Home Section5
		
		public function section5() 
	{
        if($this->session->userdata('user'))
		{
			$data['homeSection5'] = $this->HomeModel->HomeSection5List();
		    $this->load->view('layout/header_data');
			$this->load->view('layout/left_side_bar');
			$this->load->view('home-page5/home_page_list', $data);
			$this->load->view('layout/footer_data');
		}
		else
		{
			redirect('admin-login');
		}
    }
	
	
	public function add_home_section5()
    {
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page5/add');
		$this->load->view('layout/footer_data');
    }
	
    public function save_home_page_section5()
    {
		//print_r($_POST);
		//die;
		$RequestMethod = $this->input->server('REQUEST_METHOD');
        if($RequestMethod == "POST")  
		{ 
			$img_name=$this->HomeModel->home_section5_images_upload();
			$image_name=$img_name['file_name'];
			$data=array(
			
			'heading'=>$this->input->post('heading'),
			'description'=>$this->input->post('description'),
			'banner_image'=>$image_name,
						
		   );
          
			
			$success = $this->db->insert('home_section5', $data);
				$this->session->set_flashdata('success','Successfully added...');
         
				//$this->session->set_flashdata('alert', array('message' => 'Successfully added...','class' => 'success'));
				redirect('home/section5');
		   }
	
    }
	
	public function delete_section5($section_id = null)
	{
		$this->HomeModel->delete_section5($section_id);
		$this->session->set_flashdata('success','Successfully deleted...');
         
		redirect('home/section5');
	}
	
	
	public function edit_home_page_section5()
    {	
    
        $home_section5_id =  $this->uri->segment(3);
        $data['edit_home_section5'] = $this->HomeModel->get_home_page_section5_data($home_section5_id);
        $this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page5/edit', $data);
		$this->load->view('layout/footer_data');
		
    }
	
	
	function update_home_page_section5(){
			
			   //$id=$this->uri->segment(3);
			   $RequestMethod = $this->input->server('REQUEST_METHOD');

                 if($RequestMethod == "POST")  { 
                 	$section_id=$this->input->post('section_id');
					if($_FILES['banner_image']['name']=='') {
			               $image_name=$this->input->post('old_banner_image');
			               
		                  } else	{
							 /*$gallery_detais=$this->Product_Model->get_single_image($id);
				             $previous_name=$gallery_detais[0]->galley_image_name;
							 $img_file=FCPATH . '/webroot/uploads/gallery/'.$previous_name;
							 if (!unlink($img_file)) {} else { }*/
		                         $img_name=$this->HomeModel->home_section5_images_upload();
		        			 $image_name=$img_name['file_name'];
		        
						  }
			         

				$data=array(
				'heading'=>$this->input->post('heading'),
				'description'=>$this->input->post('description'),
				'banner_image'=>$image_name,
			
				);
				 
						
							$this->db->where('id',$section_id);
							$this->db->update('home_section5',$data);
							$this->session->set_flashdata('success','Successfully updated...');
         
							//$this->session->set_flashdata('alert', array('message' => 'Successfully updated... ','class' => 'success'));
							redirect('home/section5');
			   
			            }
	 	}
		
		
		
		//For Home Section6
		
		public function section6() 
	{
		$data['get_count'] = $this->HomeModel->get_count_homeSection6();
        
        if($this->session->userdata('user'))
		{
			$data['homeSection6'] = $this->HomeModel->HomeSection6List();
		    $this->load->view('layout/header_data');
			$this->load->view('layout/left_side_bar');
			$this->load->view('home-page6/home_page_list', $data);
			$this->load->view('layout/footer_data');
		}
		else
		{
			redirect('admin-login');
		}
    }
	
	
	public function add_home_section6()
    {
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page6/add');
		$this->load->view('layout/footer_data');
    }
	
    public function save_home_page_section6()
    {
		//print_r($_POST);
		//die;
		$RequestMethod = $this->input->server('REQUEST_METHOD');
        if($RequestMethod == "POST")  
		{ 
			 $data=array(
			
			'heading1'=>$this->input->post('heading1'),
			'heading2'=>$this->input->post('heading2'),
			);
          
			
			$success = $this->db->insert('home_section6', $data);
				$this->session->set_flashdata('success','Successfully added...');
         
				//$this->session->set_flashdata('alert', array('message' => 'Successfully added...','class' => 'success'));
				redirect('home/section6');
		   }
    }
	
	public function delete_section6($section_id = null)
	{
		$this->HomeModel->delete_section6($section_id);
		$this->session->set_flashdata('success','Successfully deleted...');
         
		redirect('home/section6');
	}
	
	
	public function edit_home_page_section6()
    {	
    
        $home_section6_id =  $this->uri->segment(3);
        $data['edit_home_section6'] = $this->HomeModel->get_home_page_section6_data($home_section6_id);
        $this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page6/edit', $data);
		$this->load->view('layout/footer_data');
		
    }
	
	
	function update_home_page_section6(){
			
			   //$id=$this->uri->segment(3);
			   $RequestMethod = $this->input->server('REQUEST_METHOD');

                 if($RequestMethod == "POST")  { 
                 	$section_id=$this->input->post('section_id');
			         

				$data=array(
				'heading1'=>$this->input->post('heading1'),
				'heading2'=>$this->input->post('heading2'),
				);
				 
						
							$this->db->where('id',$section_id);
							$this->db->update('home_section6',$data);
							$this->session->set_flashdata('success','Successfully updated...');
         
							//$this->session->set_flashdata('alert', array('message' => 'Successfully updated... ','class' => 'success'));
							redirect('home/section6');
			   
			            }
	 	}
		
		
		
		//For Home Section7
		
		public function section7() 
	{
        if($this->session->userdata('user'))
		{
			$data['homeSection7'] = $this->HomeModel->HomeSection7List();
		    $this->load->view('layout/header_data');
			$this->load->view('layout/left_side_bar');
			$this->load->view('home-page7/home_page_list', $data);
			$this->load->view('layout/footer_data');
		}
		else
		{
			redirect('admin-login');
		}
    }
	
	
	public function add_home_section7()
    {
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page7/add');
		$this->load->view('layout/footer_data');
    }
	
    public function save_home_page_section7()
    {
		//print_r($_POST);
		//die;
		$RequestMethod = $this->input->server('REQUEST_METHOD');
        if($RequestMethod == "POST")  
		{ 
			$img_name=$this->HomeModel->client_images_upload();
			$image_name=$img_name['file_name'];
			
			 $data=array(
			
			'client_image'=>$image_name,
			'client_name'=>$this->input->post('client_name'),
			'brand'=>$this->input->post('brand'),		   
			'description'=>$this->input->post('description'),	               
		   );
          
			
			$success = $this->db->insert('home_section7', $data);
				$this->session->set_flashdata('success','Successfully added...');
         

				//$this->session->set_flashdata('alert', array('message' => 'Successfully added...','class' => 'success'));
				redirect('home/section7');
		   }
    }
	
	public function delete_section7($section_id = null)
	{
		$this->HomeModel->delete_section7($section_id);
		$this->session->set_flashdata('success','Successfully deleted...');
         
		redirect('home/section7');
	}
	
	
	public function edit_home_page_section7()
    {	
    
        $home_section7_id =  $this->uri->segment(3);
        $data['edit_home_section7'] = $this->HomeModel->get_home_page_section7_data($home_section7_id);
        $this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page7/edit', $data);
		$this->load->view('layout/footer_data');
		
    }
	
	
	function update_home_page_section7(){
			
			   //$id=$this->uri->segment(3);
			   $RequestMethod = $this->input->server('REQUEST_METHOD');

                 if($RequestMethod == "POST")  { 
                 	$section_id=$this->input->post('section_id');
			         if($_FILES['client_image']['name']=='') {
			               $image_name=$this->input->post('old_client_image');
			               
		                  } else	{
							 /*$gallery_detais=$this->Product_Model->get_single_image($id);
				             $previous_name=$gallery_detais[0]->galley_image_name;
							 $img_file=FCPATH . '/webroot/uploads/gallery/'.$previous_name;
							 if (!unlink($img_file)) {} else { }*/
		                     $img_name=$this->HomeModel->client_images_upload();
		        			 $image_name=$img_name['file_name'];
		        
						  }

				$data=array(
				'client_image'=>$image_name,
				'client_name'=>$this->input->post('client_name'),
				'brand'=>$this->input->post('brand'),		   
				'description'=>$this->input->post('description'),	               
		   		
			
				);
				 
						
							$this->db->where('id',$section_id);
							$this->db->update('home_section7',$data);
							$this->session->set_flashdata('success','Successfully updated...');
         
							//$this->session->set_flashdata('alert', array('message' => 'Successfully updated... ','class' => 'success'));
							redirect('home/section7');
			   
			            }
	 	}
		
		
		
		//For Home Section8
		
		public function section8() 
	{
		$data['get_count'] = $this->HomeModel->get_count_homeSection8();
        if($this->session->userdata('user'))
		{
			$data['homeSection8'] = $this->HomeModel->HomeSection8List();
		    $this->load->view('layout/header_data');
			$this->load->view('layout/left_side_bar');
			$this->load->view('home-page8/home_page_list', $data);
			$this->load->view('layout/footer_data');
		}
		else
		{
			redirect('admin-login');
		}
    }
	
	
	public function add_home_section8()
    {
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page8/add');
		$this->load->view('layout/footer_data');
    }
	
    public function save_home_page_section8()
    {
		//print_r($_POST);
		//die;
		$RequestMethod = $this->input->server('REQUEST_METHOD');
        if($RequestMethod == "POST")  
		{ 
			 $data=array(
			
			'heading1'=>$this->input->post('heading1'),
			'heading2'=>$this->input->post('heading2'),
			'email'=>$this->input->post('email'),	               
		   );
          
			
			$success = $this->db->insert('home_section8', $data);
				$this->session->set_flashdata('success','Successfully added...');
         

				//$this->session->set_flashdata('alert', array('message' => 'Successfully added...','class' => 'success'));
				redirect('home/section8');
		   }
    }
	
	public function delete_section8($section_id = null)
	{
		$this->HomeModel->delete_section8($section_id);
		$this->session->set_flashdata('success','Successfully deleted...');
         
		redirect('home/section8');
	}
	
	
	public function edit_home_page_section8()
    {	
    
        $home_section8_id =  $this->uri->segment(3);
        $data['edit_home_section8'] = $this->HomeModel->get_home_page_section8_data($home_section8_id);
        $this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('home-page8/edit', $data);
		$this->load->view('layout/footer_data');
		
    }
	
	
	function update_home_page_section8(){
			
			   //$id=$this->uri->segment(3);
			   $RequestMethod = $this->input->server('REQUEST_METHOD');

                 if($RequestMethod == "POST")  { 
                 	$section_id=$this->input->post('section_id');
			         

				$data=array(
				'heading1'=>$this->input->post('heading1'),
				'heading2'=>$this->input->post('heading2'),
				'email'=>$this->input->post('email'),	               
		   	
			
				);
				 
						
							$this->db->where('id',$section_id);
							$this->db->update('home_section8',$data);
							$this->session->set_flashdata('success','Successfully updated...');
         
							//$this->session->set_flashdata('alert', array('message' => 'Successfully updated... ','class' => 'success'));
							redirect('home/section8');
			   
			            }
	 	}
	
	
	public function sociallink() 
	{
		if($this->session->userdata('user'))
		{
			$data['sociallinkData'] = $this->HomeModel->sociallinkList();
		    $this->load->view('layout/header_data');
			$this->load->view('layout/left_side_bar');
			$this->load->view('sociallink/sociallink_list', $data);
			$this->load->view('layout/footer_data');
		}
		else
		{
			redirect('admin-login');
		}
    }

	public function sociallinkadd()
    {
		$this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('sociallink/add');
		$this->load->view('layout/footer_data');
    }
	
    public function save_sociallink()
    {
		//print_r($_POST);
		//die;
		$RequestMethod = $this->input->server('REQUEST_METHOD');
        if($RequestMethod == "POST")  
		{ 
			$img_name=$this->HomeModel->home_sociallink_images_upload();
			$image_name=$img_name['file_name'];
			$data=array(

			
			'link'=>$this->input->post('link'),
			'image'=>$image_name,               
		   );
          
			
			$success = $this->db->insert('sociallink', $data);
				$this->session->set_flashdata('success','Successfully added...');
         

				//$this->session->set_flashdata('alert', array('message' => 'Successfully added...','class' => 'success'));
				redirect('home/sociallink');
		   }
    }
	
	public function delete_sociallink($section_id = null)
	{
		$this->HomeModel->delete_sociallink($section_id);
		$this->session->set_flashdata('success','Successfully deleted...');
         
		redirect('home/sociallink');
	}


		
	public function contactform_data()
    {	
    
        $data['contactform_data'] = $this->HomeModel->get_contactform_data();
        $this->load->view('layout/header_data');
		$this->load->view('layout/left_side_bar');
		$this->load->view('contact_form_list', $data);
		$this->load->view('layout/footer_data');
	}
}